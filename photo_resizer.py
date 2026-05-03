import os
import sys
from PIL import Image # type: ignore
from PIL import ImageOps # type: ignore
import argparse
from typing import Tuple, Union, List

def resize_to_target_size(image_path: str, target_kb: int, output_path: str) -> Tuple[bool, Union[int, str]]:
    """
    Resizes an image to keep it under a specific file size (KB) while maintaining aspect ratio.
    Uses a temporary file to ensure safe overwriting on Windows.
    """
    target_size = target_kb * 1024
    temp_path = f"{output_path}.tmp"
    
    try:
        if not os.path.exists(image_path):
            return False, f"File not found: {image_path}"

        with Image.open(image_path) as img:
            # Store original format before any processing (ImageOps/resize loses it)
            original_format = img.format if img.format else 'JPEG'
            
            # Handle orientation
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            
            # Normalizing extension and format
            save_format = original_format
            if save_format not in ['JPEG', 'PNG', 'WEBP']:
                save_format = 'JPEG'
            
            # User specifically asked: .jpeg -> .jpg
            base, ext = os.path.splitext(output_path)
            if ext.lower() == '.jpeg' or save_format == 'JPEG':
                if ext.lower() in ['.jpeg', '.jpg', '.png', '.webp']: # Only if it was an image ext
                    output_path = base + '.jpg'
                    temp_path = f"{output_path}.tmp"
                    save_format = 'JPEG'

            # If we are saving as JPEG but image has alpha channel (RGBA), convert to RGB
            if save_format == 'JPEG' and img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            quality: int = 95
            width: int
            height: int
            width, height = img.size
            
            # Ensure output directory exists
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)

            # Initial save to temp path
            def save_img(image, path, fmt, q):
                params = {'format': fmt}
                if fmt == 'JPEG':
                    params['quality'] = q
                elif fmt == 'PNG':
                    params['optimize'] = True
                elif fmt == 'WEBP':
                    params['quality'] = q
                image.save(path, **params)

            save_img(img, temp_path, save_format, quality)
            
            # Loop to adjust size
            while os.path.getsize(temp_path) > target_size and (quality > 10 or width > 100):
                current_size = os.path.getsize(temp_path)
                
                if current_size > target_size * 1.5 or save_format == 'PNG': # type: ignore
                    # For PNG or very large JPEG, reduce dimensions
                    reduction_factor = (target_size / current_size) ** 0.5 # type: ignore
                    width = max(100, int(width * reduction_factor * 0.9)) # type: ignore
                    height = max(100, int(height * reduction_factor * 0.9)) # type: ignore
                    img = img.resize((width, height), Image.Resampling.LANCZOS)
                else:
                    # Otherwise, reduce quality
                    quality = quality - 5 # type: ignore
                    if quality < 10:
                        width = int(width * 0.8)
                        height = int(height * 0.8)
                        img = img.resize((width, height), Image.Resampling.LANCZOS)
                        quality = 30
                
                save_img(img, temp_path, save_format, quality)
            
            # Finalize: Replace or move temp to output
            final_size = os.path.getsize(temp_path)
            
            # If we are overwriting the original file, we must ensure it's not locked.
            # Since we are inside 'with Image.open(image_path)', we should close it first if image_path == output_path.
            # But Pillow often closes it after loading if it's small, or we can just move it after the 'with' block.
        
        # Move temp to final output path after 'with' block to avoid lock issues
        if os.path.exists(output_path) and os.path.abspath(image_path) != os.path.abspath(output_path):
            os.remove(output_path) # Remove if exists and not the same as source
        
        import shutil
        shutil.move(temp_path, output_path)
        
        return True, int(final_size)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False, str(e)

def get_image_files(input_path: str, recursive: bool = False) -> List[str]:
    """Returns a list of image files from a path (file or directory)."""
    files_to_process = []
    extensions = ('.png', '.jpg', '.jpeg', '.webp')
    
    if os.path.isfile(input_path):
        if input_path.lower().endswith(extensions):
            files_to_process.append(input_path)
    elif os.path.isdir(input_path):
        if recursive:
            for root, dirs, files in os.walk(input_path):
                for f in files:
                    if f.lower().endswith(extensions):
                        files_to_process.append(os.path.join(root, f))
        else:
            for f in os.listdir(input_path):
                if f.lower().endswith(extensions):
                    files_to_process.append(os.path.join(input_path, f))
    return files_to_process

def main() -> None:
    parser = argparse.ArgumentParser(description="Batch resize photos to a target file size.")
    parser.add_argument("input", help="Path to the input directory or a single image file")
    parser.add_argument("target", type=int, help="Target file size in KB")
    parser.add_argument("--output", help="Path to the output directory", default="output")
    
    args = parser.parse_args()
    
    input_path: str = args.input
    target_kb: int = args.target
    output_dir: str = args.output
    
    files_to_process = get_image_files(input_path)
    
    if not files_to_process:
        print(f"Error: {input_path} is not a valid file or directory containing images.")
        sys.exit(1)
        
    print(f"Processing {len(files_to_process)} images to under {target_kb}KB...")
    
    success_count: int = 0
    for file_path in files_to_process:
        filename = os.path.basename(file_path)
        dest_path = os.path.join(output_dir, filename)
        
        success, result = resize_to_target_size(file_path, target_kb, dest_path)
        if success and isinstance(result, int):
            print(f"[OK] {filename}: {result/1024:.2f}KB")
            success_count = success_count + 1 # type: ignore
        else:
            print(f"[ERROR] {filename}: {result}")
            
    print(f"\nDone! Successfully processed {success_count}/{len(files_to_process)} images.")
    print(f"Results are in: {os.path.abspath(output_dir)}")

if __name__ == "__main__":
    main()
