import pyperclip
import requests
import re
from urllib.parse import quote
import sys
import json
import os
import concurrent.futures
import time

PSKOV_PROXIMITY_ORDER = [
    "FI", "LV", "BY", "LT", "EE", "PL", "UA", "SE", "NO", "DE", "CZ", "SK", "HU",
    "NL", "BE", "LU", "CH", "AT", "FR", "GB", "IE", "DK", "ES", "PT", "IT", "GR",
    "RO", "BG", "RS", "HR", "SI", "TR", "MD", "GE", "AM", "AZ", "CA", "US",
]

def load_country_map(filename="country_map.json"):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, filename)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ Файл '{filename}' не найден. Использую стандартные названия стран.")
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка декодирования JSON: {e}")
    except Exception as e:
        print(f"❌ Ошибка при чтении файла '{filename}': {e}")
    return {}

def get_flag_emoji(country_code: str) -> str:
    if not isinstance(country_code, str) or len(country_code) != 2 or not country_code.isalpha():
        return "🏁"
    # Использование индексов вместо срезов для односимвольных строк немного эффективнее
    offset = 0x1F1E6 - ord('A')
    return chr(ord(country_code[0]) + offset) + chr(ord(country_code[1]) + offset)

def get_country_info(ip_address: str, session: requests.Session):
    # Передача сессии для переиспользования соединений
    url = f'https://ipwho.is/{ip_address}'
    params = {'fields': 'country,country_code'}
    try:
        # Использование сессии для выполнения запроса
        with session.get(url, params=params, timeout=5) as response:
            response.raise_for_status()
            data = response.json()

            if not data.get('success', False):
                error_message = data.get('message', 'Неизвестная ошибка API')
                print(f"❌ API ошибка для {ip_address}: {error_message}")
                return None

            return {
                'code': data.get('country_code'),
                'name': data.get('country')
            }
    except requests.exceptions.RequestException as e:
        print(f"🌐 Сетевая ошибка для {ip_address}: {e}")
    # Нет необходимости ловить Exception, т.к. RequestException покрывает большинство случаев
    return None


def process_single_config(config_line: str, country_map: dict, session: requests.Session):
    # config_line.strip() уже вызывается в run_processing, здесь можно убрать
    ip_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', config_line)
    if not ip_match:
        # Сообщение об ошибке выводится только один раз
        return ('ZZZ', config_line)

    ip_address = ip_match.group(0)
    base_config = config_line.split('#', 1)[0].rstrip()

    country_info = get_country_info(ip_address, session)
    if not country_info or not country_info.get('code'):
        return ('ZZZ', config_line)

    country_code = country_info['code'].upper()
    country_name = country_map.get(country_code, country_info.get('name', 'Unknown'))
    
    flag = get_flag_emoji(country_code)
    new_name = f"{flag} {country_name}"
    encoded_name = quote(new_name)
    
    return country_code, f"{base_config}#{encoded_name}"

def run_processing():
    country_map = load_country_map()
    print(f"Загружено названий стран: {len(country_map)}")

    try:
        clipboard_content = pyperclip.paste().strip()
        if not clipboard_content:
            print("📋 Буфер обмена пуст")
            return
    except Exception as e:
        # В реальном приложении можно использовать tkinter как запасной вариант
        print(f"❌ Ошибка доступа к буферу обмена: {e}")
        return

    # Фильтрация пустых строк
    configs = [line for line in clipboard_content.splitlines() if line.strip()]
    if not configs:
        print("❌ Нет конфигов для обработки")
        return

    print(f"🔧 Найдено конфигов: {len(configs)}")
    print("🚀 Начинаю обработку...")
    start_time = time.time()
    
    processed_results = []
    # Использование requests.Session для переиспользования TCP-соединений
    with requests.Session() as session:
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            # Привязка future к исходной конфигурации для лучшей отладки
            future_to_config = {
                executor.submit(process_single_config, conf, country_map, session): conf 
                for conf in configs
            }
            
            for i, future in enumerate(concurrent.futures.as_completed(future_to_config)):
                config = future_to_config[future]
                try:
                    processed_results.append(future.result())
                except Exception as e:
                    print(f"⚠️ Ошибка обработки для '{config}': {e}")
                    processed_results.append(('ZZZ', config))
                
                # Более точный прогресс-бар
                if (i + 1) % 10 == 0 or (i + 1) == len(configs):
                    print(f"⏳ Обработано: {i+1}/{len(configs)}")

    print(f"⌛ Время обработки: {time.time() - start_time:.1f} сек")

    # Создание словаря для O(1) доступа к приоритетам
    priority_map = {code: idx for idx, code in enumerate(PSKOV_PROXIMITY_ORDER)}
    processed_results.sort(key=lambda x: (priority_map.get(x[0], float('inf')), x[0]))

    output_lines = [res[1] for res in processed_results]
    output_filename = 'configs.txt'
    
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(output_lines))
        print(f"💾 Результаты сохранены в {output_filename}")
    except IOError as e:
        print(f"❌ Ошибка сохранения файла '{output_filename}': {e}")

if __name__ == "__main__":
    run_processing()