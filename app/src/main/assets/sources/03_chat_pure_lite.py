import requests, base64, random, string, json, sys

def rsa_enc(m, n, e):
    ps = []
    while len(ps) < (128 - len(m) - 3):
        r = random.randint(1, 255)
        ps.append(r)
    eb = b'\x00\x02' + bytes(ps) + b'\x00' + m.encode()
    p = int.from_bytes(eb, 'big')
    c = pow(p, e, n)
    return base64.b64encode(c.to_bytes(128, 'big')).decode()

def gen_id():
    r = lambda n: ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))
    return f"{r(14)}-{r(15)}-3f700d7e-921600-{r(15)}"

def chat():
    n = 136236490358183259653189950748359669580190635598405237306311768987156534532312435393317272373703463400839797405683556405633769494895560212863113877037049039352461932992309204029954183762382698647733158589129700438379720646895034736836216527276967880354063143356560735956241651941835057143194078092683552570413
    e = 65537
    vt = rsa_enc(gen_id(), n, e)
    url = 'https://api.chattide.ai/aigc/chat/v2/professional/stream'
    h = {
        'lang': 'ar', 'vtoken': vt, 'source': 'web',
        'content-type': 'application/json',
        'accept': 'text/event-stream,application/json',
        'referer': 'https://www.chattide.ai/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    while True:
        q = input("\nانت: ")
        if q.lower() in ['exit', 'quit', 'خروج']: break
        p = {
            'spaceHandle': True, 'roleId': 0,
            'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': q}]}],
            'conversationId': None, 'model': 'gpt-5.6-luna'
        }
        try:
            r = requests.post(url, headers=h, json=p, stream=True)
            print("\nالرد: ", end="", flush=True)
            for line in r.iter_lines():
                if line:
                    d = line.decode()
                    if d.startswith("data:"):
                        txt = d[5:].strip()
                        if txt == "--@DONE@--": break
                        if txt:
                            txt = txt.replace("-=- --", " ").replace("-=-n-", "\n")
                            print(txt, end="", flush=True)
            print()
        except:
            break

if __name__ == "__main__":
    chat()
