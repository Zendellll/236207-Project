import os
from bs4 import BeautifulSoup
import re

# --- CONFIGURATION ---
INPUT_DIR = "mock_internet/manual_html"  # Upload your HTML files here
OUTPUT_DIR = "mock_internet/clean"       # Where the clean .txt files go

def clean_html_file(filepath):
    try:
        # Try opening with utf-8, fallback to latin-1 if needed
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(filepath, "r", encoding="latin-1") as f:
                content = f.read()

        soup = BeautifulSoup(content, 'html.parser')

        # 1. Remove Clutter (Scripts, Styles, Nav bars)
        for element in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe", "svg"]):
            element.extract()

        # 2. Extract Text
        text = soup.get_text(separator='\n')

        # 3. Clean Whitespace
        # Collapse multiple empty lines into one
        lines = (line.strip() for line in text.splitlines())
        clean_text = '\n'.join(chunk for chunk in lines if chunk)

        return clean_text

    except Exception as e:
        print(f"Error processing {filepath}: {e}")
        return None

def main():
    if not os.path.exists(INPUT_DIR):
        os.makedirs(INPUT_DIR)
        print(f"Created '{INPUT_DIR}'. Please upload your HTML files there.")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    files = [f for f in os.listdir(INPUT_DIR) if f.endswith((".html", ".htm", ".mhtml"))]
    print(f"--- Processing {len(files)} Manual HTML Files ---")

    for filename in files:
        input_path = os.path.join(INPUT_DIR, filename)
        
        print(f"Processing: {filename}...")
        text_content = clean_html_file(input_path)
        
        if text_content:
            # Create a consistent .txt filename
            # e.g., "tripadvisor_1.html" -> "manual_tripadvisor_1.txt"
            base_name = os.path.splitext(filename)[0]
            output_filename = f"manual_{base_name}.txt"
            output_path = os.path.join(OUTPUT_DIR, output_filename)
            
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"SOURCE_FILENAME: {filename}\n")
                f.write("-" * 50 + "\n")
                f.write(text_content)
                
            print(f"   -> Saved to {output_filename}")
        else:
            print("   -> Skipped (Empty or Error)")

    print(f"\n--- Done! Check '{OUTPUT_DIR}' for your files. ---")

if __name__ == "__main__":
    main()
