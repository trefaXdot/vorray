import json
import re
from pathlib import Path
from urllib.parse import quote, unquote
import concurrent.futures

import pyperclip
import requests
from requests.adapters import HTTPAdapter, Retry

# --- НАСТРОЙКИ ---
COUNTRY_MAP_FILENAME = "country_map.json"
OUTPUT_FILENAME = "configs.txt"
API_URL_TEMPLATE = "http://ip-api.com/json/{}?fields=status,message,country,countryCode"
API_TIMEOUT = 5
MAX_WORKERS = 10  # Количество одновременных запросов к API
FALLBACK_SORT_CODE = "ZZZ"
# Список кодов стран для сортировки по географической близости
CITY_PROXIMITY_ORDER = (
    # Прямые соседи и РФ
    "RU", "FI", "LV", "BY", "LT", "EE", "PL", "UA", 
    # Близкая Европа
    "SE", "NO", "DE", "CZ", "SK", "HU", "MD",
    # Западная и Южная Европа
    "NL", "BE", "LU", "CH", "AT", "FR", "GB", "IE", "DK",
    "ES", "PT", "IT", "GR", "RO", "BG", "RS", "HR", "SI",
    # Другие страны
    "TR", "GE", "AM", "AZ", "CA", "US", "HK", "JP", "SG"
)


def load_maps(filename: str) -> tuple[dict, dict, str] | None:
    """Загружает карту стран, обратную карту и regex-шаблон для кодов."""
    file_path = Path(__file__).resolve().parent / filename
    if not file_path.exists():
        print(f"❌ Ошибка: Файл '{filename}' не найден.")
        return None
    try:
        with file_path.open('r', encoding='utf-8') as f:
            country_map = json.load(f)
        
        # Карта для поиска по названию: {"германия": "DE", "франция": "FR"}
        reverse_country_map = {name.lower(): code for code, name in country_map.items()}
        
        # Regex для поиска кодов стран как отдельных слов: \b(DE|FR|US)\b
        country_codes_regex = r'\b(' + '|'.join(country_map.keys()) + r')\b'
        
        return country_map, reverse_country_map, country_codes_regex
    except (json.JSONDecodeError, IOError) as e:
        print(f"❌ Ошибка при чтении файла '{filename}': {e}")
        return None


def get_flag_emoji(country_code: str) -> str:
    """Генерирует флаг-эмодзи по двухбуквенному коду страны."""
    if not isinstance(country_code, str) or len(country_code) != 2 or not country_code.isalpha():
        return "🏁"
    offset = 0x1F1E6 - ord('A')
    return chr(ord(country_code[0]) + offset) + chr(ord(country_code[1]) + offset)


def create_requests_session() -> requests.Session:
    """Создает сессию requests с настроенными повторными попытками."""
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries, pool_maxsize=MAX_WORKERS)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def process_single_config(
    config_line: str,
    country_map: dict,
    reverse_country_map: dict,
    country_codes_regex: str,
    session: requests.Session
) -> tuple[str, str]:
    """
    Обрабатывает одну строку конфигурации, применяя новую логику.
    Приоритет 1: Поиск страны в названии.
    Приоритет 2: Поиск страны по IP через API.
    """
    if not config_line.strip():
        return FALLBACK_SORT_CODE, config_line

    parts = config_line.strip().split('#', 1)
    base_config = parts[0]
    remark = unquote(parts[1]) if len(parts) > 1 else ""
    found_code = None

    # --- Приоритет 1: Ищем подсказки в названии (remark) ---
    if remark:
        # Сначала ищем полное название страны (например, "Германия")
        for name_lower, code in reverse_country_map.items():
            if re.search(r'\b' + re.escape(name_lower) + r'\b', remark, re.IGNORECASE):
                found_code = code
                break
        
        # Если не нашли по полному названию, ищем код страны (например, "DE")
        if not found_code:
            match = re.search(country_codes_regex, remark, re.IGNORECASE)
            if match:
                found_code = match.group(0).upper()

    # Если нашли код в названии, формируем новую строку и выходим
    if found_code and found_code in country_map:
        country_name = country_map[found_code]
        flag = get_flag_emoji(found_code)
        new_name = f"{flag} {country_name}"
        print(f"✅  Найдено в названии: '{remark[:30]}...' -> {new_name}")
        return found_code, f"{base_config}#{quote(new_name)}"

    # --- Приоритет 2: Если в названии ничего нет, ищем по IP (старый метод) ---
    ip_match = re.search(r'@[^,:]+', base_config)
    if not ip_match:
        ip_match = re.search(r'\b((?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b', base_config)
    
    if not ip_match:
        print(f"⚠️  Ни подсказок, ни IP. Оставляю как есть: {config_line[:50]}...")
        return FALLBACK_SORT_CODE, config_line
        
    ip_address = ip_match.group(0).lstrip('@')
    
    try:
        response = session.get(API_URL_TEMPLATE.format(ip_address), timeout=API_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if data.get('status') == 'success' and data.get('countryCode'):
            country_code = data['countryCode']
            country_name = country_map.get(country_code, data.get('country', 'Неизвестно'))
            flag = get_flag_emoji(country_code)
            new_name = f"{flag} {country_name}"
            print(f"✅  Найдено по IP: {ip_address:<15} -> {new_name}")
            return country_code, f"{base_config}#{quote(new_name)}"
        else:
            api_message = data.get('message', 'нет данных')
            print(f"❌  API не определил страну для {ip_address:<15} ({api_message}).")
            return FALLBACK_SORT_CODE, config_line
            
    except requests.RequestException as e:
        print(f"❌  Ошибка сети для {ip_address:<15} ({type(e).__name__}).")
        return FALLBACK_SORT_CODE, config_line


def main():
    """Главная функция, управляющая всем процессом."""
    maps = load_maps(COUNTRY_MAP_FILENAME)
    if not maps:
        return
    country_map, reverse_country_map, country_codes_regex = maps

    try:
        clipboard_content = pyperclip.paste()
        if not clipboard_content:
            print("📋 Буфер обмена пуст. Скопируйте конфиги и запустите скрипт снова.")
            return
    except pyperclip.PyperclipException:
        print("❌ Ошибка доступа к буферу обмена.")
        return
        
    configs = clipboard_content.strip().splitlines()
    print(f"🔍 Найдено {len(configs)} конфигов. Начинаю обработку в {MAX_WORKERS} потоков...")

    processed_results = []
    session = create_requests_session()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_config = {
            executor.submit(
                process_single_config, 
                conf, 
                country_map, 
                reverse_country_map, 
                country_codes_regex, 
                session
            ): conf 
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
        output_path = Path(__file__).resolve().parent / OUTPUT_FILENAME
        try:
            with output_path.open('w', encoding='utf-8') as f:
                f.write('\n'.join(final_lines))
            print(f"\n🎉 Готово! {len(final_lines)} конфигов сохранено в файл '{output_path}'")
        except IOError as e:
            print(f"\n❌ Не удалось записать результат в файл '{output_path}': {e}")
    else:
        print("\n🤷‍♂️ Нет конфигов для сохранения.")


if __name__ == "__main__":
    main()