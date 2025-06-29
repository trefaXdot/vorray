# main.py
import asyncio
import json
import logging
import re
import sys
import urllib.parse
from pathlib import Path
from typing import List

import aiofiles
import aiohttp
import uvicorn
from fastapi import FastAPI, Body, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel

# --- КОНФИГУРАЦИЯ ---
MAX_CONCURRENT_CHECKS = 45  # Снижено до лимита ip-api.com (45/min)
BATCH_SIZE = 15             # Размер пакета запросов
BATCH_DELAY = 1             # Задержка в секундах между пакетами

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_country_data():
    country_data_path = Path("country_data.json")
    if not country_data_path.is_file():
        sys.exit(f"Критическая ошибка: Файл {country_data_path} не найден.")
    try:
        with open(country_data_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        sys.exit(f"Критическая ошибка при чтении {country_data_path}: {e}")

COUNTRY_DATA = load_country_data()

# --- Pydantic модели ---
class ServerInfo(BaseModel):
    uri: str
    country_code: str

class ScanRequest(BaseModel):
    servers: List[str]

class SaveRequest(BaseModel):
    servers: List[ServerInfo] # ОПТИМИЗАЦИЯ: Принимаем готовые данные от фронтенда

class ScanResult(BaseModel):
    status: str
    uri: str
    remarks: str
    latency: int
    country_code: str
    country: str
    flag: str  # Заменено на код страны

app = FastAPI()
semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)

# --- Вспомогательные функции ---
def get_country_info(code: str) -> dict:
    return COUNTRY_DATA.get(code.upper(), {"name_ru": "Неизвестно"})

def parse_uri_host_and_name(uri: str) -> tuple[str | None, str]:
    host, name = None, "N/A"
    try:
        match = re.search(r"@([^:/?]+)", uri)
        if match: host = match.group(1)
        name_match = re.search(r"#(.+)", uri)
        if name_match: name = urllib.parse.unquote(name_match.group(1))
    except Exception: pass
    return host, name

async def get_geolocation(host: str, session: aiohttp.ClientSession) -> dict | None:
    if not host: return None
    url = f"http://ip-api.com/json/{host}?fields=status,countryCode"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("status") == "success":
                    return {"country_code": data.get("countryCode", "ZZZ")}
    except Exception: pass
    return None

async def get_server_info(uri: str, session: aiohttp.ClientSession) -> ScanResult | None:
    async with semaphore:
        host, remarks = parse_uri_host_and_name(uri)
        if not host:
            logging.warning(f"Не удалось извлечь хост из: {uri[:50]}...")
            return None
        geo_data = await get_geolocation(host, session)
        country_code = geo_data["country_code"] if geo_data else "ZZZ"
        country_info = get_country_info(country_code)
        
        return ScanResult(
            status="SUCCESS", uri=uri, remarks=remarks, latency=0,
            country_code=country_code, country=country_info['name_ru'], flag=f"[{country_code}]" # Вместо флага - код
        )

# --- FastAPI эндпоинты ---
@app.get("/", response_class=HTMLResponse)
async def read_root(): return FileResponse("index.html")

@app.get("/style.css", response_class=FileResponse)
async def read_css(): return FileResponse("style.css")

@app.post("/scan")
async def start_scan(request: Request, payload: ScanRequest):
    async def event_stream():
        tasks = []
        async with aiohttp.ClientSession() as session:
            for i, server in enumerate(payload.servers):
                tasks.append(get_server_info(server, session))
                # ИСПРАВЛЕНО: Дросселировка запросов для избежания бана от API
                if (i + 1) % BATCH_SIZE == 0:
                    results = await asyncio.gather(*tasks)
                    for result in results:
                        if result: yield f"data: {result.json()}\n\n"
                    tasks = []
                    await asyncio.sleep(BATCH_DELAY)
            
            # Обработка оставшихся задач
            if tasks:
                results = await asyncio.gather(*tasks)
                for result in results:
                    if result: yield f"data: {result.json()}\n\n"

    from fastapi.responses import StreamingResponse
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.post("/save")
async def save_configs(payload: SaveRequest):
    output_lines = []
    # ОПТИМИЗАЦИЯ: Больше не делаем API-запросы, используем данные от фронтенда
    for server in payload.servers:
        country_info = get_country_info(server.country_code)
        # Новый формат имени: [XX] Название страны
        new_name = urllib.parse.quote(f"[{server.country_code}] {country_info['name_ru']}")
        base_uri = server.uri.split('#')[0] if '#' in server.uri else server.uri
        new_uri = f"{base_uri}#{new_name}"
        output_lines.append(new_uri)
    try:
        # ИСПРАВЛЕНО: Добавлен aiofiles
        async with aiofiles.open("configs.txt", "w", encoding="utf-8") as f:
            await f.write("\n".join(output_lines))
        return JSONResponse(content={"message": f"Успешно сохранено {len(output_lines)} конфигураций в configs.txt"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"Ошибка при сохранении файла: {e}"})

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)