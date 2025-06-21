import base64
import json
import re
import subprocess
import sys
import time
import os
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from urllib.parse import urlparse, parse_qs, unquote
import requests
from flask import Flask, render_template, request, Response, jsonify, send_from_directory
from waitress import serve

# --- Конфигурация ---
MAX_WORKERS = 30
PORT_POOL = list(range(11000, 11000 + MAX_WORKERS))
port_queue = Queue()
for port in PORT_POOL:
    port_queue.put(port)

# URL для теста (возвращает HTTP/1.1 204)
TEST_URL = "https://www.google.com/generate_204"
CONNECTION_TIMEOUT = 5

app = Flask(__name__, template_folder='.')
xray_path = "./xray.exe" if sys.platform == "win32" else "./xray"
COUNTRY_DATA_MAP = {}


def load_country_data(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"ОШИБКА при загрузке {filepath}: {e}")
        sys.exit(1)

COUNTRY_DATA_MAP = load_country_data('countries.json')


def sanitize_string(text):
    return re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', text) if isinstance(text, str) else text

# --- Парсеры URI ---
def parse_uri(uri):
    u = uri.strip()
    if not u:
        return None
    if u.startswith('vless://'):   return parse_vless_uri(u)
    if u.startswith('vmess://'):   return parse_vmess_uri(u)
    if u.startswith('ss://'):      return parse_ss_uri(u)
    if u.startswith('trojan://'):  return parse_trojan_uri(u)
    if u.startswith('hy2://') or u.startswith('hysteria2://'):
        return parse_hysteria2_uri(u)
    return None

# (include your parse_vless_uri, parse_vmess_uri, parse_ss_uri, parse_trojan_uri, parse_hysteria2_uri here unchanged)


def get_ip_info(ip):
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,message,countryCode,query", timeout=10)
        r.raise_for_status()
        d = r.json()
        if d.get('status') == 'success':
            cc = d.get('countryCode','').upper()
            info = COUNTRY_DATA_MAP.get(cc)
            if info:
                return {'country_code': cc, 'country': info['ru'], 'flag': info['flag']}
    except:
        pass
    fb = COUNTRY_DATA_MAP.get('ZZZ', {'ru':'Unknown','flag':''})
    return {'country_code':'ZZZ','country':fb['ru'],'flag':fb['flag']}


def test_server(cfg):
    port = port_queue.get()
    fn = f"temp_config_{port}.json"
    try:
        # build config
        conf = {'inbounds':[{'port':port,'protocol':'http','listen':'127.0.0.1'}], 'outbounds':[{'protocol':cfg['protocol'],'settings':{},'streamSettings':{}}]}
        out = conf['outbounds'][0]
        settings, ss, proto = out['settings'], out['streamSettings'], cfg['protocol']
        # configure according to proto as before

        with open(fn,'w',encoding='utf-8') as f:
            json.dump(conf,f)
        proc = subprocess.Popen([xray_path,'-c',fn], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.8)

        # measure SOCKS5 handshake + CONNECT
        start = time.time()
        host = urlparse(TEST_URL).hostname
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
            s.settimeout(CONNECTION_TIMEOUT)
            s.connect(('127.0.0.1',port))
            s.sendall(b"\x05\x01\x00")  # greeting
            s.recv(2)
            addr = host.encode('utf-8')
            req = b"\x05\x01\x00\x03" + bytes([len(addr)]) + addr + cfg.get('port',443).to_bytes(2,'big')
            s.sendall(req)
            s.recv(10)
            return int((time.time()-start)*1000)
    except:
        return None
    finally:
        proc.terminate(); proc.wait()
        if os.path.exists(fn): os.remove(fn)
        port_queue.put(port)


def process_uri(uri):
    cfg = parse_uri(uri)
    if not cfg: return None
    lat = test_server(cfg)
    if isinstance(lat,int):
        info = get_ip_info(cfg['host'])
        return {'status':'SUCCESS','uri':sanitize_string(uri),'remarks':sanitize_string(cfg.get('remarks','')),'country_code':info['country_code'],'country':info['country'],'flag':info['flag'],'latency':lat}
    return {'status':'FAILED','uri':sanitize_string(uri)}

@app.route('/')
def index(): return render_template('index.html')

@app.route('/style.css')
def style(): return send_from_directory('.','style.css',mimetype='text/css')

@app.route('/scan',methods=['POST'])
def scan():
    uris = request.json.get('servers',[])
    def gen():
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(process_uri,u.strip()):u for u in uris if u.strip()}
            for f in as_completed(futs):
                u0 = futs[f]
                try: r = f.result()
                except Exception as e: r = {'status':'FAILED','uri':sanitize_string(u0),'remarks':sanitize_string(str(e))}
                line = json.dumps(r,ensure_ascii=True).replace('\n',' ')
                yield f"data: {line}\n\n"
    return Response(gen(),mimetype='text/event-stream')

@app.route('/save',methods=['POST'])
def save():
    uris = request.json.get('servers',[])
    if not uris: return jsonify({'message':'Нет серверов для сохранения.'}),400
    try:
        with open('slist.txt','w',encoding='utf-8') as f: f.write('\n'.join(uris))
        return jsonify({'message':f"{len(uris)} серверов сохранено."}),200
    except Exception as e:
        return jsonify({'message':f"Ошибка: {e}"}),500

if __name__=='__main__':
    if not os.path.exists(xray_path): print(f"Xray не найден: {xray_path}"); sys.exit(1)
    print('--- Production Mode ---')
    serve(app,host='127.0.0.1',port=5001)
