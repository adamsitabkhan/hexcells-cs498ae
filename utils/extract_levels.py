import csv
import json
import hashlib
import os
import re
import requests

cache_dir = "cache_reqwest"
levels_dir = "levels"

os.makedirs(levels_dir, exist_ok=True)
os.makedirs(cache_dir, exist_ok=True)

# Regex pattern used in Rust
# (?s)(Hexcells level v1\n[^\n]*\n(?:[^\n]*\n){3}(?:(?:[^\n]*\.\.[^\n]*\n)){32}[^\n]*\.\.[^\n<]*)\n<
PATTERN = re.compile(r"(Hexcells level v1\n[^\n]*\n(?:[^\n]*\n){3}(?:(?:[^\n]*\.\.[^\n]*\n)){32}[^\n]*\.\.[^\n<]*)[\n<]")

def get_html(url):
    url = url.replace("https://www.reddit.com", "https://old.reddit.com")
    serialized = json.dumps(url)
    h = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    cache_path = os.path.join(cache_dir, h)
    
    if os.path.exists(cache_path):
        with open(cache_path, 'r') as f:
            return json.loads(f.read())
    else:
        # Fetch it
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"}
        r = requests.get(url, headers=headers)
        html = r.text
        # Save to cache
        with open(cache_path, 'w') as f:
            f.write(json.dumps(html))
        return html

def process_csv(filename):
    out_filename = filename + ".tmp"
    with open(filename, 'r', newline='') as f_in, open(out_filename, 'w', newline='') as f_out:
        reader = csv.reader(f_in)
        writer = csv.writer(f_out)
        
        header = next(reader)
        # Add new column for LocalPath
        header.append("LocalPath")
        writer.writerow(header)
        
        url_idx = header.index("URL")
        
        for row in reader:
            url = row[url_idx]
            html = get_html(url)
            matches = PATTERN.findall(html)
            
            paths = []
            for i, match in enumerate(matches):
                # Clean up match
                level_text = match.strip()
                # Create a filename based on URL hash and index
                h = hashlib.md5((url + str(i)).encode('utf-8')).hexdigest()
                level_path = os.path.join(levels_dir, f"{h}.hexcells")
                with open(level_path, 'w') as f:
                    f.write(level_text)
                paths.append(level_path)
            
            # Join multiple paths with semicolon if there are multiple puzzles in one post
            row.append(";".join(paths))
            writer.writerow(row)
            
    os.rename(out_filename, filename)

print("Processing 1puzzles_ranked.csv...")
process_csv("external/inventory/1puzzles_ranked.csv")
print("Processing 2puzzles.csv...")
process_csv("external/inventory/2puzzles.csv")
print("Done!")
