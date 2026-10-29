// Codec: https://github.com/bwrsandman/rtptool at 258d1750340917bcf1361a177b90abd16de40453.
// Its MIT license is retained in third_party/rtpatch/LICENSE.
#[path = "../third_party/rtpatch/codec.rs"]
mod codec;
use std::{env, fs};

fn main() {
    if let Err(e) = decode() {
        eprintln!("{e}");
        std::process::exit(1);
    }
}

fn decode() -> Result<(), String> {
    let args: Vec<_> = env::args_os().collect();
    if args.len() != 8 { return Err("expected input, offset, compressed size, output size, w1, w2, output".into()); }
    let mut numbers = Vec::new();
    for arg in &args[2..7] {
        numbers.push(arg.to_str().ok_or("invalid number")?.parse::<usize>().map_err(|_| "invalid number")?);
    }
    let (offset, size, expected, w1, w2) = (numbers[0], numbers[1], numbers[2], numbers[3], numbers[4]);
    let data = fs::read(&args[1]).map_err(|e| e.to_string())?;
    if offset.checked_add(size).map_or(true, |end| end > data.len()) || expected > 16 * 1024 * 1024 {
        return Err("patch record outside supported bounds".into());
    }
    let result = codec::decompress(&data, offset, size, expected + 1)?;
    if result.len() != expected { return Err("decoded size mismatch".into()); }
    let (mut actual1, mut actual2) = (0u32, 0u32);
    for &byte in &result {
        let a = actual1 ^ byte as u32;
        actual1 = ((a << 8) | (a >> 23)) & 0x7fffffff;
        let b = actual2 ^ byte as u32;
        actual2 = ((b << 8) | (b >> 22)) & 0x3fffffff;
    }
    if actual1 as usize != w1 || actual2 as usize != w2 { return Err("decoded checksum mismatch".into()); }
    fs::write(&args[7], result).map_err(|e| e.to_string())
}
