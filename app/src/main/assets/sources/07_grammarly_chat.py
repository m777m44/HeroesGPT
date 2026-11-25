import socket, ssl, json, uuid, os, base64, requests, time

def get_session():
    s = requests.Session()
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    s.get("https://www.grammarly.com/ai-chat", headers=h )
    return s, s.cookies.get_dict()

class WS:
    def __init__(self, url, cookies):
        self.url = url
        self.cookies = cookies
        self.sock = None
        self.connect()

    def connect(self):
        host = self.url.split("//")[1].split("/")[0]
        path = "/" + self.url.split("//")[1].split("/", 1)[1]
        self.sock = socket.create_connection((host, 443))
        self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=host)
        self.sock.settimeout(15)
        key = base64.b64encode(os.urandom(16)).decode()
        c_str = "; ".join([f"{k}={v}" for k, v in self.cookies.items()])
        req = (
            f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nOrigin: https://www.grammarly.com\r\n"
            f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64 ) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36\r\n"
            f"Cookie: {c_str}\r\n\r\n"
        )
        self.sock.send(req.encode())
        self.sock.recv(4096)

    def send(self, data):
        data = data.encode()
        l = len(data)
        h = bytearray([0x81])
        if l <= 125: h.append(l | 0x80)
        elif l <= 65535: h.append(126 | 0x80); h.extend(l.to_bytes(2, 'big'))
        else: h.append(127 | 0x80); h.extend(l.to_bytes(8, 'big'))
        mask = os.urandom(4)
        h.extend(mask)
        m_data = bytearray(l)
        for i in range(l): m_data[i] = data[i] ^ mask[i % 4]
        self.sock.send(h + m_data)

    def recv(self):
        try:
            h = self.sock.recv(2)
            if not h: return None
            opcode = h[0] & 0x0f
            l = h[1] & 127
            if l == 126: l = int.from_bytes(self.sock.recv(2), 'big')
            elif l == 127: l = int.from_bytes(self.sock.recv(8), 'big')
            d = b""
            while len(d) < l:
                chunk = self.sock.recv(l - len(d))
                if not chunk: break
                d += chunk
            if opcode == 0x8: return "CLOSE"
            return d.decode(errors='ignore')
        except: return None

def main():
    print("\n--- Grammarly AI Chat ---")
    print("1. دردشة عادية")
    print("2. دردشة مع ملف")
    choice = input("\nالاختيار: ")
    sess, cookies = get_session()
    file_content = ""
    if choice == "2":
        path = input("أدخل مسار الملف: ")
        if os.path.exists(path):
            url = "https://dox.grammarly.com/docproc/extract"
            h = {
                "x-csrf-token": cookies.get("csrf-token", "" ),
                "x-api-version": "2",
                "x-container-id": cookies.get("gnar_containerId", ""),
                "x-client-type": "web",
                "x-client-version": "1.0.53",
                "accept": "application/json",
                "referer": "https://www.grammarly.com/ai-chat",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64 ) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            files = {"source_file": (os.path.basename(path), open(path, "rb"), "application/octet-stream")}
            r = sess.post(url, headers=h, files=files)
            if r.status_code == 200:
                file_content = r.json().get("text", "")
                print("[+] تم استخراج نص الملف.")
            else:
                print(f"[-] خطأ في الرفع: {r.status_code}")
        else:
            print("[-] الملف غير موجود.")
    ws = WS("wss://capi.grammarly.com/freews", cookies)
    ts = int(time.time() * 1000)
    start = {"id":1,"action":"start","docid":f"funnel-ai-chat-{uuid.uuid4()}","client":"funnel","clientSubtype":"ai-chat","clientVersion":"1.0.0","dialect":"american","documentContext":{"goals":[],"audience":"general","style":"neutral","emotions":[],"domain":"general"},"clientSupports":["cheetah:124","g2_ui","assistant_file_upload:5.0.0"],"dynamicBackendUrls":{},"experimentOverrides":{},"clientConfigs":{"text_actions":{"version":"3.1.0"}},"sessionMetadata":{"userType":"anonymous","messageCount":0,"sessionStartTime":ts}}
    ws.send(json.dumps(start))
    for _ in range(5):
        m = ws.recv()
        if m and "sid" in m: break
    while True:
        p = input("\nأنت: ")
        if not p: continue
        if file_content:
            p = f"سياق من الملف:\n{file_content}\n\nسؤال: {p}"
            file_content = ""
        msg = {"id":2,"action":"text_actions:invokeCommand","correlationId":str(uuid.uuid4()),"actionId":{"id":"assistant:chatPrompt"},"args":{"userPrompt":{"json":json.dumps(p)},"conversationHistory":{"json":"[]"}},"additionalContext":{"extraProperties":{"UserAuthStatus":{"json":json.dumps({"isAnonymous":True,"messageCount":1,"timestamp":int(time.time()*1000)})}}},"entrypoint":{"name":"assistant","family":"g2"},"metadata":{},"scope":{"text":"","kind":"otherText"}}
        ws.send(json.dumps(msg))
        print("الرد: ", end="", flush=True)
        last = ""
        while True:
            m = ws.recv()
            if not m or "CLOSE" in m: break
            try:
                d = json.loads(m)
                if d.get("action") == "text_actions:commandResult":
                    res = d.get("extraProperties", {}).get("responseText", {})
                    if "json" in res:
                        t = json.loads(res["json"])
                        if t.startswith(last):
                            print(t[len(last):], end="", flush=True)
                            last = t
                    if d.get("kind") == "final": break
            except: continue
        print()

if __name__ == "__main__":
    main()