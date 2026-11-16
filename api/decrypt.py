from http.server import BaseHTTPRequestHandler
import json
import base64
import io
import requests
import pikepdf
import sys
import traceback
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

START_YEAR = 1940
END_YEAR = 2020
THREADS = 16

def gen_dob_range():
    d = date(START_YEAR, 1, 1)
    end = date(END_YEAR, 12, 31)
    step = timedelta(days=1)
    while d <= end:
        yield d.strftime("%d%m%Y")
        d += step

def brute_force_pdf_bytes(pdf_bytes):
    combos = list(gen_dob_range())
    found = {"pw": None, "data": None}
    
    def try_one(pw):
        if found["pw"]: return None
        try:
            with pikepdf.open(io.BytesIO(pdf_bytes), password=pw) as pdf:
                found["pw"] = pw
                out = io.BytesIO()
                pdf.save(out)
                found["data"] = out.getvalue()
                return pw
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futures = [ex.submit(try_one, pw) for pw in combos]
        for fut in as_completed(futures):
            if found["pw"]:
                for f2 in futures: f2.cancel()
                break
                
    return found["pw"], found["data"]

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            req = json.loads(post_data.decode('utf-8'))
            
            pdf_bytes = None
            if 'url' in req:
                headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.ckycindia.in/"}
                r = requests.get(req['url'], headers=headers, timeout=20)
                r.raise_for_status()
                pdf_bytes = r.content
            elif 'file_base64' in req:
                pdf_bytes = base64.b64decode(req['file_base64'])
            else:
                return self.reply(400, {"success": False, "error": "No URL or File provided"})
                
            if not pdf_bytes.startswith(b"%PDF-"):
                return self.reply(400, {"success": False, "error": "Invalid PDF format"})

            pw, decrypted_bytes = brute_force_pdf_bytes(pdf_bytes)
            
            if pw and decrypted_bytes:
                b64_out = base64.b64encode(decrypted_bytes).decode('utf-8')
                data_url = f"data:application/pdf;base64,{b64_out}"
                return self.reply(200, {"success": True, "password": pw, "file_data": data_url})
            else:
                return self.reply(200, {"success": False, "error": "No DOB matched in range 1940-2020."})
                
        except Exception as e:
            # Print error to Vercel logs so we can see it
            print(traceback.format_exc(), file=sys.stderr)
            return self.reply(500, {"success": False, "error": f"Server Error: {str(e)}"})

    def reply(self, code, obj):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode('utf-8'))
