import pyperclip
import requests
import re
from urllib.parse import quote
import sys
import json
import os
import concurrent.futures

# СПИСОК СОРТИРОВКИ ПО БЛИЗОСТИ К ПСКОВУ
PSKOV_PROXIMITY_ORDER = [
    "RU", "EE", "LV", "BY", "LT", "FI", "PL", "UA", "SE", "NO", "DE",
    "CZ", "SK", "HU", "NL", "BE", "LU", "CH", "AT", "FR", "GB", "IE",
    "DK", "ES", "PT", "IT", "GR", "RO", "BG", "RS", "HR", "SI", "TR",
    "MD", "GE", "AM", "AZ", "CA", "US",
]

def load_country_map(filename="country_map.json"):
    """Загружает карту стран из JSON-файла."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, filename)
    if not os.path.exists(file_path):
        print(f"❌ Ошибка: Файл '{filename}' не найден.")
        return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Ошибка при чтении файла '{filename}': {e}")
        return None

def get_flag_emoji(country_code: str) -> str:
    """Генерирует эмодзи флага по коду страны."""
    if not country_code or len(country_code) != 2 or not country_code.isalpha():
        return "🏁"
    offset = 0x1F1E6 - ord('A')
    return chr(ord(country_code.upper()[0]) + offset) + chr(ord(country_code.upper()[1]) + offset)

def process_single_config(config_line, country_map):
    """
    Обрабатывает ОДНУ строку конфига, используя стандарт индустрии — ipinfo.io.
    Возвращает кортеж (код страны, новая строка конфига) для последующей сортировки.
    """
    if not config_line.strip():
        return ('ZZZ', config_line)

    ip_match = re.search(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', config_line)
    if not ip_match:
        print(f"⚠️  IP не найден, оставляю как есть: {config_line[:50]}...")
        return ('ZZZ', config_line)

    ip_address = ip_match.group(0)
    base_config = config_line.split('#')[0]

    try:
        # --- ИЗМЕНЕНИЕ ЗДЕСЬ: Используем самый надежный API ipinfo.io ---
        api_url = f'https://ipinfo.io/{ip_address}/json'
        # Добавляем стандартный User-Agent, так как ipinfo.io этого требует
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(api_url, timeout=4, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        # Поле с кодом страны в ответе ipinfo.io называется 'country'
        country_code = data.get('country')
        if country_code:
            country_name_ru = country_map.get(country_code, data.get('country', 'Неизвестно'))
            flag = get_flag_emoji(country_code)
            new_name = f"{flag} {country_name_ru}"
            
            encoded_new_name = quote(new_name)
            new_config_line = f"{base_config}#{encoded_new_name}"
            print(f"✅  {ip_address} -> {new_name}")
            return (country_code, new_config_line)
        else:
            print(f"❌  API не вернул страну для IP {ip_address}. Оставляю как есть.")
            return ('ZZZ', config_line)
    except requests.RequestException:
        print(f"❌  Ошибка сети или IP не найден для {ip_address}. Оставляю как есть.")
        return ('ZZZ', config_line)
    except json.JSONDecodeError:
        print(f"❌  API вернул некорректный ответ для {ip_address}. Оставляю как есть.")
        return ('ZZZ', config_line)

def run_processing():
    """Главная функция, управляющая всем процессом."""
    country_map = load_country_map()
    if not country_map:
        return

    try:
        clipboard_content = pyperclip.paste()
        if not clipboard_content:
            print("Буфер обмена пуст. Скопируйте конфиги и запустите скрипт снова.")
            return
    except pyperclip.PyperclipException:
        print("Ошибка доступа к буферу обмена. Убедитесь, что установлена графическая среда.")
        return
        
    configs = clipboard_content.strip().splitlines()
    print(f"Найдено {len(configs)} конфигов. Начинаю параллельную обработку...")

    processed_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_config = {executor.submit(process_single_config, conf, country_map): conf for conf in configs}
        for future in concurrent.futures.as_completed(future_to_config):
            try:
                processed_results.append(future.result())
            except Exception as e:
                print(f"Критическая ошибка при обработке конфига: {e}")

    print("\nСортировка результатов по списку приоритета...")
    
    priority_map = {code: i for i, code in enumerate(PSKOV_PROXIMITY_ORDER)}
    processed_results.sort(key=lambda res: (priority_map.get(res[0], float('inf')), res[0]))

    final_lines = [res[1] for res in processed_results]

    if final_lines:
        output_filename = 'configs.txt'
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(final_lines))
        print(f"\n🎉 Готово! {len(final_lines)} конфигов обработано, отсортировано и сохранено в '{output_filename}'")
    else:
        print("Нет конфигов для сохранения.")


if __name__ == "__main__":
    run_processing()