use std::collections::HashMap;
use std::io::Cursor;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::atomic::{AtomicU32, Ordering};

use base64::Engine;
use image::{DynamicImage, GrayImage, Luma, Rgba, RgbaImage, imageops::FilterType};
use ort::session::Session;
use ort::value::Tensor as OrtTensor;
use serde::{Deserialize, Serialize};
use tauri::Emitter;

// ── State ────────────────────────────────────────────────────────────────────

struct RawResult {
    pixels: Vec<u8>, // flat RGBA, no alpha clean applied
    width: u32,
    height: u32,
}

struct ModelCache {
    sessions: Mutex<HashMap<String, Session>>,
    last_raw: Mutex<Option<RawResult>>,
}

impl ModelCache {
    fn new() -> Self {
        Self {
            sessions: Mutex::new(HashMap::new()),
            last_raw: Mutex::new(None),
        }
    }
}

// Incremented each time a new auto flow starts; stale sim callbacks check this.
static SIM_GEN: AtomicU32 = AtomicU32::new(0);

// ── Combo / candidate types ───────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Combo {
    pub key: String,
    pub model: String,
    pub post_process: bool,
    pub alpha_clean: bool,
    pub alpha_matting: bool,
    pub label: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SimResult {
    gen: u32,
    key: String,
    label: String,
    base64_png: Option<String>, // None = error
    error: Option<String>,
}

// ── Model path ────────────────────────────────────────────────────────────────

fn get_model_path(model_name: &str) -> Option<PathBuf> {
    let filename = format!("{}.onnx", model_name);
    if let Ok(exe) = std::env::current_exe() {
        if let Some(p) = exe.parent() {
            let p = p.join("models").join(&filename);
            if p.exists() { return Some(p); }
        }
    }
    let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()?.parent()?.join("models").join(&filename);
    if dev.exists() { return Some(dev); }
    None
}

fn input_size_for(model_name: &str) -> u32 {
    match model_name { "isnet-general-use" => 1024, _ => 320 }
}

fn ensure_session<'a>(
    sessions: &'a mut HashMap<String, Session>,
    model_name: &str,
) -> Result<&'a mut Session, String> {
    if !sessions.contains_key(model_name) {
        let model_path = get_model_path(model_name)
            .ok_or_else(|| format!("모델 파일 없음: {model_name}.onnx"))?;
        let session = Session::builder()
            .map_err(|e| e.to_string())?
            .commit_from_file(&model_path)
            .map_err(|e| format!("모델 로드 실패: {e}"))?;
        sessions.insert(model_name.to_owned(), session);
    }
    Ok(sessions.get_mut(model_name).unwrap())
}

// ── Preprocessing ─────────────────────────────────────────────────────────────

fn preprocess(img: &DynamicImage, size: u32) -> Vec<f32> {
    let resized = img.resize_exact(size, size, FilterType::Triangle);
    let rgb = resized.to_rgb8();
    let mean = [0.485_f32, 0.456, 0.406];
    let std  = [0.229_f32, 0.224, 0.225];
    let s = size as usize;
    let mut data = vec![0.0_f32; 3 * s * s];
    for (x, y, pixel) in rgb.enumerate_pixels() {
        let (xi, yi) = (x as usize, y as usize);
        data[yi * s + xi]             = (pixel[0] as f32 / 255.0 - mean[0]) / std[0];
        data[s * s + yi * s + xi]     = (pixel[1] as f32 / 255.0 - mean[1]) / std[1];
        data[2 * s * s + yi * s + xi] = (pixel[2] as f32 / 255.0 - mean[2]) / std[2];
    }
    data
}

// ── Morphological operations ──────────────────────────────────────────────────

fn morph_dilate(img: &GrayImage, half: i32) -> GrayImage {
    let (w, h) = (img.width() as i32, img.height() as i32);
    let mut out = GrayImage::new(img.width(), img.height());
    for y in 0..h {
        for x in 0..w {
            let mut max_v = 0u8;
            for ky in -half..=half {
                for kx in -half..=half {
                    let nx = (x + kx).clamp(0, w - 1) as u32;
                    let ny = (y + ky).clamp(0, h - 1) as u32;
                    max_v = max_v.max(img.get_pixel(nx, ny)[0]);
                }
            }
            out.put_pixel(x as u32, y as u32, Luma([max_v]));
        }
    }
    out
}

fn morph_erode(img: &GrayImage, half: i32) -> GrayImage {
    let (w, h) = (img.width() as i32, img.height() as i32);
    let mut out = GrayImage::new(img.width(), img.height());
    for y in 0..h {
        for x in 0..w {
            let mut min_v = 255u8;
            for ky in -half..=half {
                for kx in -half..=half {
                    let nx = (x + kx).clamp(0, w - 1) as u32;
                    let ny = (y + ky).clamp(0, h - 1) as u32;
                    min_v = min_v.min(img.get_pixel(nx, ny)[0]);
                }
            }
            out.put_pixel(x as u32, y as u32, Luma([min_v]));
        }
    }
    out
}

fn post_process_mask(mask: GrayImage) -> GrayImage {
    let binary = GrayImage::from_fn(mask.width(), mask.height(), |x, y| {
        Luma([if mask.get_pixel(x, y)[0] > 127 { 255 } else { 0 }])
    });
    let closed = morph_erode(&morph_dilate(&binary, 2), 2);
    morph_dilate(&morph_erode(&closed, 1), 1)
}

// ── Alpha clean ───────────────────────────────────────────────────────────────

fn do_alpha_clean(rgba: &RgbaImage, enabled: bool, lo: u8, hi: u8) -> RgbaImage {
    if !enabled { return rgba.clone(); }
    let (w, h) = (rgba.width(), rgba.height());
    let mut result = RgbaImage::new(w, h);
    for (x, y, pixel) in rgba.enumerate_pixels() {
        let a = pixel[3];
        let a = if a <= lo { 0 } else if a >= hi { 255 }
                else { ((a - lo) as f32 / (hi - lo) as f32 * 255.0) as u8 };
        result.put_pixel(x, y, Rgba([pixel[0], pixel[1], pixel[2], a]));
    }
    result
}

// ── Core inference pipeline ───────────────────────────────────────────────────

// Returns raw RGBA (no alpha clean) so the caller can apply it separately.
fn run_pipeline_raw(
    session: &mut Session,
    img: &DynamicImage,
    model_name: &str,
    do_post_process: bool,
) -> Result<RgbaImage, String> {
    let (orig_w, orig_h) = (img.width(), img.height());
    let size = input_size_for(model_name);
    let flat = preprocess(img, size);
    let shape = vec![1_i64, 3, size as i64, size as i64];
    let ort_input: OrtTensor<f32> = OrtTensor::from_array((shape, flat))
        .map_err(|e| e.to_string())?;

    let outputs = session.run(ort::inputs![ort_input])
        .map_err(|e| format!("추론 실패: {e}"))?;

    let (shape_out, raw) = outputs[0]
        .try_extract_tensor::<f32>()
        .map_err(|e| e.to_string())?;
    let n = shape_out.len();
    let (mh, mw) = (shape_out[n - 2] as usize, shape_out[n - 1] as usize);

    let sigmoid: Vec<f32> = raw.iter().map(|&x| 1.0 / (1.0 + (-x).exp())).collect();
    let min = sigmoid.iter().cloned().fold(f32::INFINITY, f32::min);
    let max = sigmoid.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
    let range = (max - min).max(1e-6);
    let mut gray = GrayImage::new(mw as u32, mh as u32);
    for (i, &v) in sigmoid.iter().enumerate() {
        let norm = ((v - min) / range * 255.0).round().clamp(0.0, 255.0) as u8;
        gray.put_pixel((i % mw) as u32, (i / mw) as u32, Luma([norm]));
    }

    if do_post_process { gray = post_process_mask(gray); }

    let mask = DynamicImage::ImageLuma8(gray)
        .resize_exact(orig_w, orig_h, FilterType::Lanczos3)
        .to_luma8();

    let rgba_orig = img.to_rgba8();
    let mut result = RgbaImage::new(orig_w, orig_h);
    for (x, y, pixel) in rgba_orig.enumerate_pixels() {
        let a = mask.get_pixel(x, y)[0];
        result.put_pixel(x, y, Rgba([pixel[0], pixel[1], pixel[2], a]));
    }
    Ok(result)
}

fn run_pipeline(
    session: &mut Session,
    img: &DynamicImage,
    model_name: &str,
    do_post_process: bool,
    alpha_clean: bool,
    lo: u8,
    hi: u8,
) -> Result<RgbaImage, String> {
    let raw = run_pipeline_raw(session, img, model_name, do_post_process)?;
    Ok(do_alpha_clean(&raw, alpha_clean, lo, hi))
}

// ── Image analysis for Auto Selector ─────────────────────────────────────────

fn compute_edge_density(img: &DynamicImage) -> f64 {
    let small = img.thumbnail(256, 256).to_luma8();
    let (w, h) = (small.width() as i32, small.height() as i32);
    let mut above = 0u32;
    let total = (w * h) as u32;
    for y in 1..h - 1 {
        for x in 1..w - 1 {
            let gx = small.get_pixel((x+1) as u32, y as u32)[0] as i32
                   - small.get_pixel((x-1) as u32, y as u32)[0] as i32;
            let gy = small.get_pixel(x as u32, (y+1) as u32)[0] as i32
                   - small.get_pixel(x as u32, (y-1) as u32)[0] as i32;
            let mag = ((gx * gx + gy * gy) as f64).sqrt();
            if mag > 50.0 { above += 1; }
        }
    }
    above as f64 / total as f64
}

fn compute_skin_ratio(img: &DynamicImage) -> f64 {
    let small = img.thumbnail(256, 256).to_rgb8();
    let total = small.width() * small.height();
    let mut skin = 0u32;
    for (_, _, pixel) in small.enumerate_pixels() {
        let (r, g, b) = (pixel[0] as i32, pixel[1] as i32, pixel[2] as i32);
        let max_c = r.max(g).max(b);
        let min_c = r.min(g).min(b);
        if r > 95 && g > 40 && b > 20
            && (max_c - min_c) > 15
            && (r - g).abs() > 15
            && r > g && r > b
        {
            skin += 1;
        }
    }
    skin as f64 / total as f64
}

fn pick_candidates(edge_density: f64, skin_ratio: f64) -> Vec<Combo> {
    let likely_human = skin_ratio > 0.04;
    let complex_edges = edge_density > 0.10;

    let all: &[(&str, &str, bool, bool, bool, &str)] = &[
        ("isnet_balanced",  "isnet-general-use", true,  true,  false, "스탠다드"),
        ("isnet_matting",   "isnet-general-use", true,  true,  false, "정밀 경계"),
        ("human_balanced",  "u2net_human_seg",   true,  true,  false, "인물"),
        ("human_matting",   "u2net_human_seg",   true,  true,  false, "인물 정밀"),
        ("u2net_fast",      "u2net",             true,  true,  false, "쾌속"),
        ("isnet_soft",      "isnet-general-use", false, true,  false, "소프트"),
    ];

    let order: &[&str] = if likely_human {
        if complex_edges {
            &["human_balanced", "human_matting", "isnet_matting", "u2net_fast"]
        } else {
            &["human_balanced", "isnet_balanced", "u2net_fast", "isnet_soft"]
        }
    } else if complex_edges {
        &["isnet_balanced", "isnet_matting", "u2net_fast", "isnet_soft"]
    } else {
        &["isnet_balanced", "u2net_fast", "isnet_soft", "human_balanced"]
    };

    order.iter().take(4).filter_map(|&key| {
        all.iter().find(|r| r.0 == key).map(|r| Combo {
            key: r.0.to_owned(), model: r.1.to_owned(),
            post_process: r.2, alpha_clean: r.3, alpha_matting: r.4,
            label: r.5.to_owned(),
        })
    }).collect()
}

fn encode_rgba_base64(img: &RgbaImage) -> Result<String, String> {
    let mut buf = Vec::new();
    img.write_to(&mut Cursor::new(&mut buf), image::ImageFormat::Png)
        .map_err(|e| e.to_string())?;
    Ok(format!("data:image/png;base64,{}", base64::engine::general_purpose::STANDARD.encode(&buf)))
}

// ── Commands ──────────────────────────────────────────────────────────────────

#[tauri::command]
fn analyze_image(image_path: String) -> Result<Vec<Combo>, String> {
    let img = image::open(&image_path)
        .map_err(|e| format!("이미지 로드 실패: {e}"))?;
    let edge = compute_edge_density(&img);
    let skin = compute_skin_ratio(&img);
    Ok(pick_candidates(edge, skin))
}

#[tauri::command]
fn start_simulations(
    app: tauri::AppHandle,
    state: tauri::State<'_, ModelCache>,
    image_path: String,
    candidates: Vec<Combo>,
) -> Result<u32, String> {
    let gen = SIM_GEN.fetch_add(1, Ordering::SeqCst) + 1;

    let state_inner = state.inner() as *const ModelCache as usize; // raw ptr for thread
    let app_clone = app.clone();

    std::thread::spawn(move || {
        // SAFETY: AppState lives for the duration of the app
        let cache = unsafe { &*(state_inner as *const ModelCache) };

        // Load original once, thumbnail for simulation
        let Ok(orig) = image::open(&image_path) else { return; };
        let sim_img = {
            let mut s = orig.clone();
            if s.width().max(s.height()) > 4096 { s = s.thumbnail(4096, 4096); }
            let max_dim = s.width().max(s.height());
            if max_dim > 512 {
                s.thumbnail(512, 512)
            } else { s }
        };

        for combo in &candidates {
            if SIM_GEN.load(Ordering::SeqCst) != gen { break; } // cancelled

            let result = (|| -> Result<String, String> {
                let mut sessions = cache.sessions.lock().map_err(|e| e.to_string())?;
                let session = ensure_session(&mut sessions, &combo.model)?;
                let rgba = run_pipeline(session, &sim_img, &combo.model,
                                        combo.post_process, combo.alpha_clean, 80, 200)?;
                encode_rgba_base64(&rgba)
            })();

            let payload = SimResult {
                gen,
                key: combo.key.clone(),
                label: combo.label.clone(),
                base64_png: result.as_ref().ok().cloned(),
                error: result.err(),
            };
            let _ = app_clone.emit("sim-result", &payload);
        }

        let _ = app_clone.emit("sim-complete", gen);
    });

    Ok(gen)
}

#[tauri::command]
fn cancel_simulations() {
    SIM_GEN.fetch_add(1, Ordering::SeqCst);
}

#[tauri::command]
fn remove_background(
    state: tauri::State<'_, ModelCache>,
    image_path: String,
    model_name: String,
    post_process_mask: bool,
    alpha_clean: bool,
    alpha_clean_lo: u8,
    alpha_clean_hi: u8,
    #[allow(unused_variables)] alpha_matting: bool,
) -> Result<String, String> {
    let mut orig = image::open(&image_path)
        .map_err(|e| format!("이미지 로드 실패: {e}"))?;
    if orig.width().max(orig.height()) > 4096 { orig = orig.thumbnail(4096, 4096); }
    let (w, h) = (orig.width(), orig.height());

    let mut sessions = state.sessions.lock().map_err(|e| e.to_string())?;
    let session = ensure_session(&mut sessions, &model_name)?;
    let raw = run_pipeline_raw(session, &orig, &model_name, post_process_mask)?;
    drop(sessions);

    // Store raw result for reapply without re-inference
    let pixels = raw.to_vec();
    *state.last_raw.lock().map_err(|e| e.to_string())? = Some(RawResult { pixels, width: w, height: h });

    let result = do_alpha_clean(&raw, alpha_clean, alpha_clean_lo, alpha_clean_hi);
    encode_rgba_base64(&result)
}

#[tauri::command]
fn reapply_alpha_clean(
    state: tauri::State<'_, ModelCache>,
    alpha_clean: bool,
    alpha_clean_lo: u8,
    alpha_clean_hi: u8,
) -> Result<String, String> {
    let guard = state.last_raw.lock().map_err(|e| e.to_string())?;
    let raw = guard.as_ref().ok_or("처리된 이미지가 없습니다.")?;

    let rgba = RgbaImage::from_raw(raw.width, raw.height, raw.pixels.clone())
        .ok_or("이미지 복원 실패")?;
    let result = do_alpha_clean(&rgba, alpha_clean, alpha_clean_lo, alpha_clean_hi);
    encode_rgba_base64(&result)
}

#[tauri::command]
fn save_result(
    app: tauri::AppHandle,
    base64_png: String,
    bg_color: Option<String>,
    format: String,
    suggested_name: String,
) -> Result<(), String> {
    use tauri_plugin_dialog::DialogExt;

    let data_part = base64_png.splitn(2, ',').nth(1).unwrap_or(&base64_png);
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(data_part).map_err(|e| e.to_string())?;
    let rgba: RgbaImage = image::load_from_memory(&bytes)
        .map_err(|e| e.to_string())?.to_rgba8();

    let save_img: RgbaImage = match &bg_color {
        Some(hex) => {
            let h = hex.trim_start_matches('#');
            let r = u8::from_str_radix(&h[0..2], 16).unwrap_or(255);
            let g = u8::from_str_radix(&h[2..4], 16).unwrap_or(255);
            let b = u8::from_str_radix(&h[4..6], 16).unwrap_or(255);
            let (w, h2) = (rgba.width(), rgba.height());
            let mut out = RgbaImage::new(w, h2);
            for (x, y, pixel) in rgba.enumerate_pixels() {
                let a = pixel[3] as f32 / 255.0;
                out.put_pixel(x, y, Rgba([
                    (pixel[0] as f32 * a + r as f32 * (1.0 - a)) as u8,
                    (pixel[1] as f32 * a + g as f32 * (1.0 - a)) as u8,
                    (pixel[2] as f32 * a + b as f32 * (1.0 - a)) as u8,
                    255,
                ]));
            }
            out
        }
        None => rgba,
    };

    let ext = if format == "webp" { "webp" } else { "png" };
    let path = app.dialog().file()
        .set_title("Save image")
        .set_file_name(&format!("{suggested_name}.{ext}"))
        .add_filter(if format == "webp" { "WebP" } else { "PNG" }, &[ext])
        .blocking_save_file();

    if let Some(p) = path {
        let path = p.into_path().map_err(|e| e.to_string())?;
        let fmt = if format == "webp" { image::ImageFormat::WebP } else { image::ImageFormat::Png };
        save_img.save_with_format(&path, fmt).map_err(|e| e.to_string())?;
    }
    Ok(())
}

// ── App entry ─────────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(ModelCache::new())
        .invoke_handler(tauri::generate_handler![
            analyze_image, start_simulations, cancel_simulations,
            remove_background, reapply_alpha_clean, save_result
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
