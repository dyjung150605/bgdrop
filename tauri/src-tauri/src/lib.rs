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
    // Production: models/ next to executable
    if let Ok(exe) = std::env::current_exe() {
        if let Some(p) = exe.parent() {
            let p = p.join("models").join(&filename);
            if p.exists() { return Some(p); }
        }
    }
    // Dev: CARGO_MANIFEST_DIR is tauri/src-tauri/ → up 2 = BgDrop/
    let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()?.parent()?.join("models").join(&filename);
    if dev.exists() { return Some(dev); }
    None
}

fn input_size_for(model_name: &str) -> u32 {
    match model_name {
        "isnet-general-use" => 1024,
        _ => 320, // u2net, u2net_human_seg
    }
}

// ── Preprocessing — returns flat Vec<f32> in NCHW order ──────────────────────

fn preprocess(img: &DynamicImage, size: u32) -> Vec<f32> {
    let resized = img.resize_exact(size, size, FilterType::Lanczos3);
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

// ── Postprocessing ────────────────────────────────────────────────────────────

fn build_alpha_mask(raw: &[f32], mask_h: usize, mask_w: usize, orig_w: u32, orig_h: u32) -> GrayImage {
    let sigmoid: Vec<f32> = raw.iter().map(|&x| 1.0 / (1.0 + (-x).exp())).collect();
    let min = sigmoid.iter().cloned().fold(f32::INFINITY, f32::min);
    let max = sigmoid.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
    let range = (max - min).max(1e-6);
    let mut gray = GrayImage::new(mask_w as u32, mask_h as u32);
    for (i, &v) in sigmoid.iter().enumerate() {
        let norm = ((v - min) / range * 255.0).round().clamp(0.0, 255.0) as u8;
        gray.put_pixel((i % mask_w) as u32, (i / mask_w) as u32, Luma([norm]));
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

fn encode_png_base64(img: &RgbaImage) -> Result<String, String> {
    let mut buf = Vec::new();
    img.write_to(&mut Cursor::new(&mut buf), image::ImageFormat::Png)
        .map_err(|e| e.to_string())?;
    Ok(format!(
        "data:image/png;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(&buf)
    ))
}

// ── Tauri command ─────────────────────────────────────────────────────────────

#[tauri::command]
fn remove_background(
    state: tauri::State<'_, ModelCache>,
    image_path: String,
    model_name: String,
) -> Result<String, String> {
    // Load & downscale if needed
    let mut orig = image::open(&image_path)
        .map_err(|e| format!("이미지 로드 실패: {e}"))?;
    if orig.width().max(orig.height()) > 4096 {
        orig = orig.thumbnail(4096, 4096);
    }
    let (orig_w, orig_h) = (orig.width(), orig.height());

    // Resolve model path
    let model_path = get_model_path(&model_name).ok_or_else(|| {
        format!("모델 파일 없음: {model_name}.onnx\nmodels/ 폴더에 파일을 넣어주세요.")
    })?;

    // Get or create session
    let mut sessions = state.sessions.lock().map_err(|e| e.to_string())?;
    if !sessions.contains_key(&model_name) {
        let session = Session::builder()
            .map_err(|e| format!("ORT 빌더 실패: {e}"))?
            .commit_from_file(&model_path)
            .map_err(|e| format!("모델 로드 실패: {e}"))?;
        sessions.insert(model_name.clone(), session);
    }
    let session = sessions.get_mut(&model_name).unwrap();

    // Preprocess → (shape: Vec<i64>, data: Vec<f32>)
    // OwnedTensorArrayData is implemented for (D: ToShape, Vec<T>)
    let size = input_size_for(&model_name);
    let flat_data = preprocess(&orig, size);
    let shape = vec![1_i64, 3, size as i64, size as i64];
    let ort_input: OrtTensor<f32> = OrtTensor::from_array((shape, flat_data))
        .map_err(|e| format!("텐서 생성 실패: {e}"))?;

    // Inference — inputs! without name uses positional matching
    let outputs = session
        .run(ort::inputs![ort_input])
        .map_err(|e| format!("추론 실패: {e}"))?;

    // Extract mask — try_extract_tensor returns (&Shape, &[f32])
    // Shape derefs to SmallVec<[i64; 4]>
    let (shape_out, raw_slice) = outputs[0]
        .try_extract_tensor::<f32>()
        .map_err(|e| e.to_string())?;
    let n = shape_out.len();
    let (mask_h, mask_w) = (shape_out[n - 2] as usize, shape_out[n - 1] as usize);

    // Postprocess
    let mask = build_alpha_mask(raw_slice, mask_h, mask_w, orig_w, orig_h);
    let result = apply_mask(&orig, &mask, true);
    encode_png_base64(&result)
}

// ── App entry ─────────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(ModelCache::new())
        .invoke_handler(tauri::generate_handler![remove_background])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
