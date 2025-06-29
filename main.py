import json
import os
import re
from pathlib import Path
from urllib.parse import quote
import concurrent.futures

import pyperclip
import requests
from requests.adapters import HTTPAdapter, Retry
COUNTRY_MAP_FILENAME = "country_map.json"
OUTPUT_FILENAME = "configs.txt"
API_URL_TEMPLATE = "http://ip-api.com/json/{}?fields=status,message,country,countryCode"
API_TIMEOUT = 5
MAX_WORKERS = 10
FALLBACK_SORT_CODE = "ZZZ"
CITY_PROXIMITY_ORDER = (
    # Прямые соседи и РФ
    "FI", "LV", "BY", "LT", "EE",
    # Близкая Европа
    "PL", "UA", "SE", "NO", "DE", "CZ", "SK", "HU",
    # Западная и Южная Европа
    "NL", "BE", "LU", "CH", "AT", "FR", "GB", "IE", "DK",
    "ES", "PT", "IT", "GR", "RO", "BG", "RS", "HR", "SI",
    # Другие страны
    "TR", "MD", "GE", "AM", "AZ", "CA", "US",
)


def load_country_map(filename: str) -> dict | None:
    file_path = Path(__file__).resolve().parent / filename
    if not file_path.exists():
        print(f"❌ Ошибка: Файл '{filename}' не найден по пути '{file_path}'.")
        return None
    try:
        with file_path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"❌ Ошибка при чтении или парсинге файла '{filename}': {e}")
        return None


def get_flag_emoji(country_code: str) -> str:
    if not isinstance(country_code, str) or len(country_code) != 2 or not country_code.isalpha():
        return "🏁"
    
    offset = 0x1F1E6 - ord('A')
    return chr(ord(country_code.upper()[0]) + offset) + chr(ord(country_code.upper()[1]) + offset)


def create_requests_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def process_single_config(config_line: str, country_map: dict, session: requests.Session) -> tuple[str, str]:
    if not config_line.strip():
        return (FALLBACK_SORT_CODE, config_line)

    ip_match = re.search(r'\b((?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b', config_line)
    if not ip_match:
        print(f"⚠️  IP не найден, оставляю как есть: {config_line[:50]}...")
        return (FALLBACK_SORT_CODE, config_line)

    ip_address = ip_match.group(0)
    base_config = config_line.split('#')[0].strip()

    try:
        response = session.get(API_URL_TEMPLATE.format(ip_address), timeout=API_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if data.get('status') == 'success':
            country_code = data.get('countryCode')
            country_name = country_map.get(country_code, data.get('country', 'Неизвестно'))
            flag = get_flag_emoji(country_code)
            new_name = f"{flag} {country_name}"
            
            encoded_new_name = quote(new_name)
            new_config_line = f"{base_config}#{encoded_new_name}"
            
            print(f"✅  {ip_address:<15} -> {new_name}")
            return (country_code, new_config_line)
        else:
            api_message = data.get('message', 'нет данных')
            print(f"❌  API не определил страну для {ip_address:<15} ({api_message}).")
            return (FALLBACK_SORT_CODE, config_line)
            
    except requests.RequestException as e:
        print(f"❌  Ошибка сети для {ip_address:<15} ({type(e).__name__}).")
        return (FALLBACK_SORT_CODE, config_line)


def main():
    """Главная функция, управляющая всем процессом."""
    country_map = load_country_map(COUNTRY_MAP_FILENAME)
    if not country_map:
        return

    try:
        clipboard_content = pyperclip.paste()
        if not clipboard_content:
            print("📋 Буфер обмена пуст. Скопируйте конфиги и запустите скрипт снова.")
            return
    except pyperclip.PyperclipException:
        print("❌ Ошибка доступа к буферу обмена. Убедитесь, что установлена графическая среда (xclip/xsel в Linux).")
        return
        
    configs = clipboard_content.strip().splitlines()
    print(f"🔍 Найдено {len(configs)} конфигов. Начинаю обработку в {MAX_WORKERS} потоков...")

    processed_results = []
    session = create_requests_session()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_config = {
            executor.submit(process_single_config, conf, country_map, session): conf 
            for conf in configs
        }
        for future in concurrent.futures.as_completed(future_to_config):
            try:
                processed_results.append(future.result())
            except Exception as e:
                print(f"💥 Критическая ошибка при обработке конфига: {e}")

    print("\n🔄 Сортировка результатов по списку приоритета...")
    
    priority_map = {code: i for i, code in enumerate(CITY_PROXIMITY_ORDER)}
    processed_results.sort(key=lambda res: (priority_map.get(res[0], float('inf')), res[0]))
    
    final_lines = [res[1] for res in processed_results]

    if final_lines:
        try:
            with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
                f.write('\n'.join(final_lines))
            print(f"\n🎉 Готово! {len(final_lines)} конфигов сохранено в файл '{OUTPUT_FILENAME}'")
        except IOError as e:
            print(f"\n❌ Не удалось записать результат в файл '{OUTPUT_FILENAME}': {e}")
    else:
        print("\n🤷‍♂️ Нет конфигов для сохранения.")


if __name__ == "__main__":
    main()