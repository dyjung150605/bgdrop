use std::collections::HashMap;
use std::io::Cursor;
use std::path::PathBuf;
use std::sync::Mutex;

use base64::Engine;
use image::{DynamicImage, GrayImage, Luma, Rgba, RgbaImage, imageops::FilterType};
use ort::session::Session;
use ort::value::Tensor as OrtTensor;

// ── State ────────────────────────────────────────────────────────────────────

struct ModelCache {
    sessions: Mutex<HashMap<String, Session>>,
}

impl ModelCache {
    fn new() -> Self {
        Self { sessions: Mutex::new(HashMap::new()) }
    }
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
    match model_name {
        "isnet-general-use" => 1024,
        _ => 320,
    }
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

// ── Morphological operations for post-process mask ────────────────────────────

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
    // Binarize at 127
    let binary = GrayImage::from_fn(mask.width(), mask.height(), |x, y| {
        Luma([if mask.get_pixel(x, y)[0] > 127 { 255 } else { 0 }])
    });
    // Morphological close (dilate → erode): fills small holes
    let closed = morph_erode(&morph_dilate(&binary, 2), 2);
    // Morphological open (erode → dilate): removes small isolated blobs
    morph_dilate(&morph_erode(&closed, 1), 1)
}

// ── Postprocessing ────────────────────────────────────────────────────────────

fn build_alpha_mask(
    raw: &[f32],
    mask_h: usize,
    mask_w: usize,
    orig_w: u32,
    orig_h: u32,
    do_post_process: bool,
) -> GrayImage {
    let sigmoid: Vec<f32> = raw.iter().map(|&x| 1.0 / (1.0 + (-x).exp())).collect();
    let min = sigmoid.iter().cloned().fold(f32::INFINITY, f32::min);
    let max = sigmoid.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
    let range = (max - min).max(1e-6);

    let mut gray = GrayImage::new(mask_w as u32, mask_h as u32);
    for (i, &v) in sigmoid.iter().enumerate() {
        let norm = ((v - min) / range * 255.0).round().clamp(0.0, 255.0) as u8;
        gray.put_pixel((i % mask_w) as u32, (i / mask_w) as u32, Luma([norm]));
    }

    if do_post_process {
        gray = post_process_mask(gray);
    }

    DynamicImage::ImageLuma8(gray)
        .resize_exact(orig_w, orig_h, FilterType::Lanczos3)
        .to_luma8()
}

fn apply_mask(orig: &DynamicImage, mask: &GrayImage, alpha_clean: bool) -> RgbaImage {
    let rgba = orig.to_rgba8();
    let (w, h) = (rgba.width(), rgba.height());
    let mut result = RgbaImage::new(w, h);
    let (lo, hi) = (80u8, 200u8);
    for (x, y, pixel) in rgba.enumerate_pixels() {
        let a = mask.get_pixel(x, y)[0];
        let a = if alpha_clean {
            if a <= lo { 0 } else if a >= hi { 255 }
            else { ((a - lo) as f32 / (hi - lo) as f32 * 255.0) as u8 }
        } else { a };
        result.put_pixel(x, y, Rgba([pixel[0], pixel[1], pixel[2], a]));
    }
    result
}

fn composite_over_color(rgba: &RgbaImage, hex_color: &str) -> RgbaImage {
    let hex = hex_color.trim_start_matches('#');
    let r = u8::from_str_radix(&hex[0..2], 16).unwrap_or(255);
    let g = u8::from_str_radix(&hex[2..4], 16).unwrap_or(255);
    let b = u8::from_str_radix(&hex[4..6], 16).unwrap_or(255);
    let (w, h) = (rgba.width(), rgba.height());
    let mut result = RgbaImage::new(w, h);
    for (x, y, pixel) in rgba.enumerate_pixels() {
        let a = pixel[3] as f32 / 255.0;
        let nr = (pixel[0] as f32 * a + r as f32 * (1.0 - a)) as u8;
        let ng = (pixel[1] as f32 * a + g as f32 * (1.0 - a)) as u8;
        let nb = (pixel[2] as f32 * a + b as f32 * (1.0 - a)) as u8;
        result.put_pixel(x, y, Rgba([nr, ng, nb, 255]));
    }
    result
}

fn encode_png_base64(img: &RgbaImage) -> Result<String, String> {
    let mut buf = Vec::new();
    img.write_to(&mut Cursor::new(&mut buf), image::ImageFormat::Png)
        .map_err(|e| e.to_string())?;
    Ok(format!("data:image/png;base64,{}", base64::engine::general_purpose::STANDARD.encode(&buf)))
}

// ── Commands ──────────────────────────────────────────────────────────────────

#[tauri::command]
fn remove_background(
    state: tauri::State<'_, ModelCache>,
    image_path: String,
    model_name: String,
    post_process_mask: bool,
    alpha_clean: bool,
    // alpha_matting: placeholder — complex to port (pymatting), reserved for future
    #[allow(unused_variables)] alpha_matting: bool,
) -> Result<String, String> {
    let mut orig = image::open(&image_path)
        .map_err(|e| format!("이미지 로드 실패: {e}"))?;
    if orig.width().max(orig.height()) > 4096 {
        orig = orig.thumbnail(4096, 4096);
    }
    let (orig_w, orig_h) = (orig.width(), orig.height());

    let model_path = get_model_path(&model_name).ok_or_else(|| {
        format!("모델 파일 없음: {model_name}.onnx\nmodels/ 폴더에 파일을 넣어주세요.")
    })?;

    let mut sessions = state.sessions.lock().map_err(|e| e.to_string())?;
    if !sessions.contains_key(&model_name) {
        let session = Session::builder()
            .map_err(|e| format!("ORT 빌더 실패: {e}"))?
            .commit_from_file(&model_path)
            .map_err(|e| format!("모델 로드 실패: {e}"))?;
        sessions.insert(model_name.clone(), session);
    }
    let session = sessions.get_mut(&model_name).unwrap();

    let size = input_size_for(&model_name);
    let flat_data = preprocess(&orig, size);
    let shape = vec![1_i64, 3, size as i64, size as i64];
    let ort_input: OrtTensor<f32> = OrtTensor::from_array((shape, flat_data))
        .map_err(|e| format!("텐서 생성 실패: {e}"))?;

    let outputs = session
        .run(ort::inputs![ort_input])
        .map_err(|e| format!("추론 실패: {e}"))?;

    let (shape_out, raw_slice) = outputs[0]
        .try_extract_tensor::<f32>()
        .map_err(|e| e.to_string())?;
    let n = shape_out.len();
    let (mask_h, mask_w) = (shape_out[n - 2] as usize, shape_out[n - 1] as usize);

    let mask = build_alpha_mask(raw_slice, mask_h, mask_w, orig_w, orig_h, post_process_mask);
    let result = apply_mask(&orig, &mask, alpha_clean);
    encode_png_base64(&result)
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

    let save_img = match &bg_color {
        Some(color) => composite_over_color(&rgba, color),
        None => rgba,
    };

    let ext = if format == "webp" { "webp" } else { "png" };
    let path = app.dialog().file()
        .set_title("Save image")
        .set_file_name(&format!("{suggested_name}.{ext}"))
        .add_filter(if format == "webp" { "WebP" } else { "PNG" }, &[ext])
        .blocking_save_file();

    let path = match path {
        Some(p) => p.into_path().map_err(|e| e.to_string())?,
        None => return Ok(()),
    };

    let fmt = if format == "webp" { image::ImageFormat::WebP } else { image::ImageFormat::Png };
    save_img.save_with_format(&path, fmt).map_err(|e| e.to_string())
}

// ── App entry ─────────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(ModelCache::new())
        .invoke_handler(tauri::generate_handler![remove_background, save_result])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
