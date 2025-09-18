import os
import json
import uuid
import asyncio
import aiohttp
from flask import Flask, request, jsonify, send_file, Response

app = Flask(__name__, static_folder='', static_url_path='')
URLS_FILE = "urls.txt"
FILTERS_FILE = "filters.json"
TEMP_DIR = "temp"

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)
if not os.path.exists(URLS_FILE):
    with open(URLS_FILE, "w") as f:
        pass

async def fetch_url(session, url):
    try:
        async with session.get(url, timeout=20) as response:
            if response.status == 200:
                return await response.text()
            print(f"Warning: URL {url} returned status {response.status}")
            return None
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def is_valid_config(line):
    line = line.strip()
    return line.startswith(("vmess://", "vless://", "trojan://", "ss://", "ssr://"))

@app.route("/")
def serve_index():
    return app.send_static_file("index.html")

@app.route("/api/urls", methods=['GET'])
def get_urls():
    try:
        with open(URLS_FILE, "r", encoding="utf-8") as f:
            urls = f.read()
        return jsonify(urls=urls)
    except FileNotFoundError:
        return jsonify(urls="")

@app.route('/api/save_urls', methods=['POST'])
def save_urls():
    data = request.json
    urls_text = data.get('urls', '')
    with open(URLS_FILE, "w", encoding="utf-8") as f:
        f.write(urls_text)
    return jsonify(message="Список URL успешно сохранен")

@app.route('/api/step1_process', methods=['POST'])
def step1_process_and_deduplicate():
    try:
        with open(URLS_FILE, "r", encoding="utf-8") as f:
            urls = [url.strip() for url in f.readlines() if url.strip()]
        if not urls:
            return jsonify(error="Список URL пуст. Добавьте источники."), 400
    except FileNotFoundError:
        return jsonify(error="Файл с URL не найден."), 500
    result = asyncio.run(process_urls_async(urls))
    return jsonify(result)

async def process_urls_async(urls):
    all_configs_raw = set()
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_url(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
        
        for content in results:
            if content:
                for line in content.splitlines():
                    if is_valid_config(line):
                        all_configs_raw.add(line.strip())
    
    # ИЗМЕНЕНИЕ 4: Считаем общее количество до дедупликации
    total_count = len(all_configs_raw)

    unique_configs = {}
    for config in all_configs_raw:
        base, *_ = config.split("#", 1)
        if base not in unique_configs:
            unique_configs[base] = config

    final_list = list(unique_configs.values())
    
    session_id = str(uuid.uuid4())
    temp_filepath = os.path.join(TEMP_DIR, f"{session_id}.txt")
    with open(temp_filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(final_list))

    # ИЗМЕНЕНИЕ 4: Возвращаем оба значения
    return {
        "sessionId": session_id,
        "totalCount": total_count,
        "uniqueCount": len(final_list)
    }

@app.route('/api/step2_filter', methods=['POST'])
def step2_filter_configs():
    data = request.json
    session_id = data.get('sessionId')
    filters_to_apply = data.get('filters', [])
    
    if not session_id or not os.path.exists(os.path.join(TEMP_DIR, f"{session_id}.txt")):
        return jsonify(error="Invalid session"), 400

    with open(FILTERS_FILE, "r", encoding="utf-8") as f:
        all_filters = json.load(f)
    
    patterns_to_remove = []
    for f_key in filters_to_apply:
        patterns_to_remove.extend(all_filters.get(f_key, []))
    
    input_filepath = os.path.join(TEMP_DIR, f"{session_id}.txt")
    with open(input_filepath, "r", encoding="utf-8") as f:
        configs = f.readlines()
    
    # ИЗМЕНЕНИЕ 4: Считаем количество до фильтрации
    initial_count = len(configs)
    
    filtered_configs = []
    for config in configs:
        name_part = config.split("#", 1)[1] if "#" in config else ""
        config_name_lower = name_part.lower()
        should_remove = False
        for pattern in patterns_to_remove:
            if pattern in config_name_lower:
                should_remove = True
                break
        if not should_remove:
            filtered_configs.append(config.strip())
            
    output_filepath = os.path.join(TEMP_DIR, f"{session_id}_filtered.txt")
    with open(output_filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(filtered_configs))
    
    # ИЗМЕНЕНИЕ 4: Возвращаем оба значения
    return jsonify({
        "initialCount": initial_count,
        "finalCount": len(filtered_configs)
    })

@app.route('/api/step3_download/<session_id>', methods=['GET'])
def step3_download_file(session_id):
    filtered_filepath = os.path.join(TEMP_DIR, f"{session_id}_filtered.txt")
    original_filepath = os.path.join(TEMP_DIR, f"{session_id}.txt")

    if not os.path.exists(filtered_filepath):
        return "File not found or session expired.", 404

    with open(filtered_filepath, "r", encoding="utf-8") as f:
        num_lines = sum(1 for line in f if line.strip())

    filename = f"{num_lines}.txt"
    
    def generate_and_cleanup():
        with open(filtered_filepath, "rb") as f:
            yield from f
        try:
            os.remove(filtered_filepath)
            if os.path.exists(original_filepath):
                os.remove(original_filepath)
        except OSError as e:
            print(f"Error cleaning up files for session {session_id}: {e}")

    response = Response(generate_and_cleanup(), mimetype='text/plain')
    response.headers.set("Content-Disposition", "attachment", filename=filename)
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=True)