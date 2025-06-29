import pyperclip
import requests
import re
from urllib.parse import quote
import sys
import json
import os
import concurrent.futures
import time

# СПИСОК СОРТИРОВКИ ПО БЛИЗОСТИ К ПСКОВУ
PSKOV_PROXIMITY_ORDER = [
    "FI", "LV", "BY", "LT", "EE",
    "PL", "UA", "SE", "NO", "DE", "CZ", "SK", "HU",
    "NL", "BE", "LU", "CH", "AT", "FR", "GB", "IE", "DK",
    "ES", "PT", "IT", "GR", "RO", "BG", "RS", "HR", "SI",
    "TR", "MD", "GE", "AM", "AZ", "CA", "US",
]

def load_country_map(filename="country_map.json"):
    """Загружает карту стран из JSON-файла с обработкой ошибок."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, filename)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ Файл '{filename}' не найден. Использую стандартные названия стран.")
    except Exception as e:
        print(f"❌ Ошибка при чтении файла: {e}")
    return {}

def get_flag_emoji(country_code: str) -> str:
    """Генерирует эмодзи флага по коду страны."""
    if not country_code or len(country_code) != 2 or not country_code.isalpha():
        return "🏁"
    offset = 0x1F1E6 - ord('A')
    return chr(ord(country_code.upper()[0]) + offset) + chr(ord(country_code.upper()[1]) + offset)

def get_country_info(ip_address, country_map):
    """Получает информацию о стране через ipwho.is API."""
    try:
        response = requests.get(
            f'https://ipwho.is/{ip_address}',
            params={'fields': 'country,country_code'},
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        
        if not data.get('success'):
            error = data.get('message', 'Неизвестная ошибка API')
            print(f"❌ API ошибка для {ip_address}: {error}")
            return None
        
        return {
            'code': data.get('country_code'),
            'name': data.get('country')
        }
    except requests.RequestException as e:
        print(f"🌐 Сетевая ошибка для {ip_address}: {str(e)}")
    except Exception as e:
        print(f"⚠️ Неожиданная ошибка для {ip_address}: {str(e)}")
    return None

def process_single_config(config_line, country_map):
    """Обрабатывает одну строку конфига с улучшенной обработкой ошибок."""
    if not config_line.strip():
        return ('ZZZ', config_line)

    # Улучшенное регулярное выражение для поиска IP
    ip_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', config_line)
    if not ip_match:
        print(f"🔍 IP не найден: {config_line[:50]}{'...' if len(config_line) > 50 else ''}")
        return ('ZZZ', config_line)

    ip_address = ip_match.group(0)
    base_config = config_line.split('#')[0].rstrip()

    country_info = get_country_info(ip_address, country_map)
    if not country_info:
        return ('ZZZ', config_line)

    country_code = country_info['code'].upper() if country_info['code'] else '??'
    country_name = country_map.get(country_code, country_info['name'])
    
    flag = get_flag_emoji(country_code)
    new_name = f"{flag} {country_name}"
    encoded_name = quote(new_name)
    
    return (
        country_code,
        f"{base_config}#{encoded_name}"
    )

def run_processing():
    """Главная функция с улучшенной обработкой ошибок."""
    country_map = load_country_map()
    print("Загружено названий стран:", len(country_map))

    try:
        clipboard_content = pyperclip.paste().strip()
        if not clipboard_content:
            print("📋 Буфер обмена пуст")
            return
    except Exception as e:
        print(f"❌ Ошибка буфера: {str(e)}")
        return

    configs = clipboard_content.splitlines()
    print(f"🔧 Найдено конфигов: {len(configs)}")
    
    if not configs:
        print("❌ Нет конфигов для обработки")
        return

    print("🚀 Начинаю обработку...")
    start_time = time.time()
    processed_results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(process_single_config, conf, country_map) for conf in configs]
        
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            try:
                processed_results.append(future.result())
                if (i + 1) % 10 == 0:
                    print(f"⏳ Обработано: {i+1}/{len(configs)}")
            except Exception as e:
                print(f"⚠️ Ошибка обработки: {str(e)}")
                processed_results.append(('ZZZ', configs[i]))

    print(f"⌛ Время обработки: {time.time() - start_time:.1f} сек")

    # Сортировка по кастомному порядку
    priority_map = {code: idx for idx, code in enumerate(PSKOV_PROXIMITY_ORDER)}
    processed_results.sort(key=lambda x: (
        priority_map.get(x[0], float('inf')),
        x[0]
    ))

    # Сохранение результатов
    output_lines = [res[1] for res in processed_results]
    output_filename = 'configs.txt'
    
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(output_lines))
        print(f"💾 Результаты сохранены в {output_filename}")
    except Exception as e:
        print(f"❌ Ошибка сохранения: {str(e)}")

if __name__ == "__main__":
    run_processing()