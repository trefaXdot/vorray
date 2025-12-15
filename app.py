import os
import json
import uuid
import asyncio
import aiohttp
import base64
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
                text = await response.text()
                return {"url": url, "content": text, "status": "ok", "code": 200}
            return {"url": url, "content": "", "status": "error", "code": response.status}
    except Exception as e:
        return {"url": url, "content": "", "status": "error", "error_msg": str(e)}

def is_valid_config(line):
    line = line.strip()
    # ДОБАВЛЕНО: socks5://, socks:// и на всякий случай wireguard://
    return line.startswith(("vmess://", "vless://", "trojan://", "ss://", "ssr://", "hysteria2://", "hy2://", "socks5://", "socks://", "wireguard://"))
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
def step1_process():
    try:
        data = request.json or {}
        # ДОБАВЛЕНО: Чтение флага дедупликации (по умолчанию True)
        deduplicate = data.get('deduplicate', True)
        
        with open(URLS_FILE, "r", encoding="utf-8") as f:
            urls = [url.strip() for url in f.readlines() if url.strip()]
        if not urls:
            return jsonify(error="Список URL пуст. Добавьте источники."), 400
    except FileNotFoundError:
        return jsonify(error="Файл с URL не найден."), 500
    
    result = asyncio.run(process_urls_async(urls, deduplicate))
    return jsonify(result)

def try_decode_base64(content):
    content = content.strip()
    # Если контент уже похож на конфиг (начинается с vless/vmess и т.д.), не трогаем его
    if is_valid_config(content):
        return content
        
    try:
        # Base64 часто требует padding (символы = в конце), если длина не кратна 4
        missing_padding = len(content) % 4
        if missing_padding:
            content += '=' * (4 - missing_padding)
            
        decoded_bytes = base64.b64decode(content)
        decoded_str = decoded_bytes.decode('utf-8', errors='ignore')
        return decoded_str
    except Exception:
        # Если произошла ошибка декодирования, возвращаем исходный текст
        return content

async def process_urls_async(urls, deduplicate):
    collected_configs = []
    stats = []

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_url(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
        
        for res in results:
            url_stats = {
                "url": res["url"],
                "status": res.get("status", "error"),
                "count": 0,
                "msg": res.get("error_msg") or str(res.get("code", ""))
            }
            
            if res["status"] == "ok" and res["content"]:
                # Пытаемся декодировать Base64 перед разбивкой на строки
                decoded_content = try_decode_base64(res["content"])
                
                # Некоторые подписки разделяют конфиги пробелами, а не переносом строки
                # Сначала разбиваем по строкам, потом каждую строку проверяем на пробелы
                raw_lines = decoded_content.splitlines()
                valid_lines = []
                
                for raw_line in raw_lines:
                    # Иногда в одной строке base64 может быть 'vmess://... vless://...' через пробел
                    possible_configs = raw_line.split(' ')
                    for item in possible_configs:
                        if is_valid_config(item):
                            valid_lines.append(item.strip())
                
                url_stats["count"] = len(valid_lines)
                collected_configs.extend(valid_lines)
            
            stats.append(url_stats)
    
    # Логика дедупликации
    if deduplicate:
        unique_map = {}
        for config in collected_configs:
            # Ключом является часть до # (сам конфиг), значение — полная строка
            base, *_ = config.split("#", 1)
            if base not in unique_map:
                unique_map[base] = config
        final_list = list(unique_map.values())
    else:
        final_list = collected_configs

    session_id = str(uuid.uuid4())
    temp_filepath = os.path.join(TEMP_DIR, f"{session_id}.txt")
    with open(temp_filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(final_list))

    return {
        "sessionId": session_id,
        "totalFound": len(collected_configs), # Сколько всего нашли
        "uniqueCount": len(final_list),       # Сколько осталось после обработки
        "stats": stats                        # Детальная статистика
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
    
    return jsonify({
        "initialCount": initial_count,
        "finalCount": len(filtered_configs)
    })

# ДОБАВЛЕНО: Роут для получения контента (для кнопки Копировать)
@app.route('/api/get_content/<session_id>', methods=['GET'])
def get_content(session_id):
    filtered_filepath = os.path.join(TEMP_DIR, f"{session_id}_filtered.txt")
    if not os.path.exists(filtered_filepath):
        return "Session expired", 404
    
    with open(filtered_filepath, "r", encoding="utf-8") as f:
        return f.read()

@app.route('/api/step3_download/<session_id>', methods=['GET'])
def step3_download_file(session_id):
    filtered_filepath = os.path.join(TEMP_DIR, f"{session_id}_filtered.txt")
    
    if not os.path.exists(filtered_filepath):
        return "File not found or session expired.", 404

    with open(filtered_filepath, "r", encoding="utf-8") as f:
        num_lines = sum(1 for line in f if line.strip())

    filename = f"{num_lines}_configs.txt"
    
    # ИЗМЕНЕНО: Не удаляем файл сразу, чтобы можно было и скачать, и скопировать.
    # Файлы перезаписываются/удаляются логикой ОС или при рестарте (опционально)
    return send_file(filtered_filepath, as_attachment=True, download_name=filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=True)