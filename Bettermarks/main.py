import os
import time
import base64
import requests
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
import sys
import warnings
import difflib

try:
    from google import genai
    from PIL import Image
except ImportError:
    pass

# --- CONFIG ---
USER = os.getenv("SP_USERNAME") or os.getenv("SP_USER")
PASS = os.getenv("SP_PASSWORD")

if not USER or not PASS:
    print("FEHLER: SP_USERNAME oder SP_PASSWORD Umgebungsvariablen nicht gefunden!")
    sys.exit(1)

# --- KI EINSTELLUNGEN ---
AI_PROVIDER = "ollama" # 'ollama' oder 'gemini'

# OLLAMA Config
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen3.5:4b"

# GEMINI Config
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Map für die Bettermarks-Bildschirmtastatur
KEYBOARD_MAP = {
    '0': 'keyboard-0', '1': 'keyboard-1', '2': 'keyboard-2', '3': 'keyboard-3',
    '4': 'keyboard-4', '5': 'keyboard-5',    '+': 'keyboard-add', '-': 'keyboard-subtract',
    '*': 'keyboard-multiply', '/': 'keyboard-divide',
    '^': 'keyboard-exponent', '=': 'keyboard-equals',
    '(': 'keyboard-paren-left', ')': 'keyboard-paren-right',
    'x': 'keyboard-var-x', 'y': 'keyboard-var-y',
    ',': 'keyboard-comma', '.': 'keyboard-comma', '/': 'keyboard-fraction'
}

def normalize_chars(s):
    if not s: return ""
    # Ersetze mathematische Sonderzeichen durch Standardzeichen für besseren Vergleich
    s = s.replace('–', '-').replace('—', '-').replace('−', '-') # Verschiedene Dashes
    s = s.replace('·', '*').replace('×', '*').replace('⋅', '*') # Multiplikation
    # Entferne Exponenten-Zeichen und ALLE Leerzeichen für MathML-Flach-Vergleich
    # (x^2 wird in der UI oft als x2 ausgegeben)
    s = s.replace('^', '').replace(' ', '').replace('\u2060', '') # inkl. Word Joiner
    return s.strip().lower()

def solve_with_ai(image_path):    
    prompt = (
        "Löse die Matheaufgabe im Bild. Beachte die Fragestellung ganz genau. "
        "1. MULTIPLE-CHOICE (Optionen): Antworte AUSSCHLIESSLICH mit dem exakten Text der richtigen Option. "
        "2. SORTIEREN: Schreibe die Texte in richtiger vertikaler Reihenfolge (von oben nach unten), jedes Element auf einer neuen Zeile! "
        "3. LÜCKEN / ZUORDNEN (Elemente in leere Boxen/Kästen ziehen): Schreibe die Texte der Elemente in der visuellen Reihenfolge der Lücken, in die sie gezogen werden sollen (immer von oben nach unten, von links nach rechts lesen). Pro Zeile ein Element! "
        "4. EINGABEFELDER / DROPDOWNS: Wenn leere Textfelder existieren (z.B. f(x)=x^2 [ + ] [ 4 ]), "
        "   antworte AUSSCHLIESSLICH mit den exakten Werten für ALLE Felder (links nach rechts)! "
        "   Schreibe JEDES Feld in eine neue Zeile! (Beispiel: 1. Zeile: -, 2. Zeile: 4). "
        "   Ganze Potenzen: Basis^Exponent (z.B. 8^3). Wenn NUR der Exponent gesucht ist, nur die Zahl. "
        "5. GRAPHEN (Punkte/Strecken): Antworte AUSSCHLIESSLICH mit den Koordinaten der Punkte! "
        "   Jeder Punkt in eine neue Zeile, exakt im Format: x,y (z.B. 1,4 \\n 2,3). Keine Klammern, keine Sätze!"
        "Antworte IMMER nur mit der genauen Lösung, ohne Sätze, ohne Erklärungen und ohne Punkt am Ende! "
        "Wenn es mehrere Felder sind, jeden Wert in eine neue Zeile. "
        "Format-Beispiel: \n minus \n -12"
    )
    
    if AI_PROVIDER == "gemini":
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            img = Image.open(image_path)
            model = client.models.get("gemini-1.5-flash")
            res = model.generate_content(
                contents=[prompt, img]
            ).text
            
            # Cleaning Gemini
            res = res.replace('`', '').replace('Answer:', '').replace('Lösung:', '').strip()
            # Nur die Zeilen behalten, die nicht nach Prosa klingen
            lines = [l.strip() for l in res.split('\n') if l.strip()]
            filtered = []
            for l in lines:
                if len(l.split()) > 6: continue # Überspringe Sätze
                filtered.append(l)
            return "\n".join(filtered)
        except Exception as e:
            print(f"   KI Fehler (Gemini): {e}")
            return None
            
    else: # OLLAMA
        try:
            with open(image_path, "rb") as f:
                base64_image = base64.b64encode(f.read()).decode('utf-8')
            
            payload = {
                "model": "qwen3.5:4b",
                "prompt": prompt + " (STRICT: NO SENTENCES, NO INTRO/OUTRO, ONLY RAW VALUES)",
                "stream": False,
                "images": [base64_image]
            }
            response = requests.post(OLLAMA_URL, json=payload, timeout=180)
            data = response.json()
            if 'response' not in data:
                print(f"   KI Fehler (Ollama): {data.get('error', 'Unbekannter Fehler')}")
                return None
            
            raw = data['response']
            # --- ROBUSTER OLLAMA PARSER ---
            # Suche nach Schlüsselwörtern
            if "Answer:" in raw: raw = raw.split("Answer:")[-1]
            elif "Lösung:" in raw: raw = raw.split("Lösung:")[-1]
            
            # Bereinigen von Markdown
            raw = raw.replace('`', '').replace('*', '').strip()
            
            # Filtere nach echten Werten
            lines = [l.strip() for l in raw.split('\n') if l.strip()]
            final_lines = []
            for l in lines:
                # Entferne Label-Präfixe wie "Dropdown:" oder "Box:"
                clean_l = l
                if ":" in l:
                    possible_val = l.split(":")[-1].strip()
                    if possible_val: clean_l = possible_val
                
                # Wenn die Zeile zu lang ist (Satz), überspringe sie
                if len(clean_l.split()) > 5: continue
                # Wenn es eine Aufzählung ist (1.), nimm nur den Rest
                if clean_l.startswith(("1.", "2.", "3.")):
                    clean_l = clean_l[2:].strip()
                
                if clean_l: final_lines.append(clean_l)
            
            return "\n".join(final_lines)
        except Exception as e:
            print(f"   KI Fehler (Ollama Request): {e}")
            return None

def cdp_click(driver, element):
    # Sicherer echter Klick über ActionChains (isTrusted=true), um Bot-Erkennung zu vermeiden.
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(0.1)
    ActionChains(driver).move_to_element(element).click().perform()

def cdp_click_coord(driver, x, y):
    # Echter physischer Browser-Klick auf den absoluten Viewport-Pixel (W3C Actions, isTrusted=true)
    pointer = PointerInput(interaction.POINTER_MOUSE, "mouse")
    action = ActionBuilder(driver, mouse=pointer)
    action.pointer_action.move_to_location(int(x), int(y))
    action.pointer_action.click()
    action.perform()

def run_bot():
    print("Starte Chrome...")
    options = Options()
    options.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 20)

    try:
        # LOGIN
        driver.get("https://schulportal.berlin.de/start")
        wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "swift_cn_login"))).click()
        wait.until(EC.presence_of_element_located((By.ID, "username"))).send_keys(USER)
        driver.find_element(By.ID, "password").send_keys(PASS)
        driver.find_element(By.ID, "kc-login").click()

        # BETTERMARKS
        print("Öffne Bettermarks...")
        wait.until(EC.element_to_be_clickable((By.XPATH, "//img[@title='bettermarks']"))).click()
        time.sleep(3)
        driver.switch_to.window(driver.window_handles[-1])

        while True:
            # SUCHE NEUE SERIE (OHNE STERN)
            driver.switch_to.default_content()
            print("\nSuche nächste Aufgabe ohne Stern...")
            time.sleep(3)
            start_xpath = "//button[contains(., 'Start') or contains(., 'start')] | //a[contains(., 'Start') or contains(., 'start')] | //*[@role='button' and (contains(., 'Start') or contains(., 'start'))] | //*[@data-cy='ActionButton-start']"
            local_start_xpath = ".//button[contains(., 'Start') or contains(., 'start')] | .//a[contains(., 'Start') or contains(., 'start')] | .//*[@role='button' and (contains(., 'Start') or contains(., 'start'))] | .//*[@data-cy='ActionButton-start']"
            
            start_buttons = driver.find_elements(By.XPATH, start_xpath)
            print(f"[{len(start_buttons)} Start-Buttons in der Übersicht gefunden]")
            found_new_series = False
            
            for index, btn in enumerate(start_buttons):
                has_star = False
                parent = btn
                for level in range(1, 8):
                    try:
                        parent = parent.find_element(By.XPATH, "..")
                        starts_in_parent = parent.find_elements(By.XPATH, local_start_xpath)
                        if len(starts_in_parent) > 1:
                            break
                        
                        # Prüfe per XPath auf Stern
                        stars = parent.find_elements(By.XPATH, ".//*[local-name()='path' and starts-with(@d, 'M2.87706')]")
                        if stars:
                            print(f"   -> Start-Button {index + 1} hat einen Stern (wird übersprungen).")
                            has_star = True
                            break
                            
                        # Sicherheit-Fallback: Prüfe Attribute direkt per Python
                        all_svgs = parent.find_elements(By.XPATH, ".//*[local-name()='path' or local-name()='svg']")
                        for svg in all_svgs:
                            d = svg.get_attribute("d") or ""
                            fill = svg.get_attribute("fill") or ""
                            if "2.877" in d or "FFDD66" in fill.upper() or "FFD700" in fill.upper():
                                print(f"   -> Start-Button {index + 1} hat einen Stern (Fallback-Match).")
                                has_star = True
                                break
                        if has_star:
                            break
                    except:
                        break
                
                if not has_star:
                    if btn.is_displayed():
                        print(f"Start-Button {index + 1} hat KEINEN Stern und ist sichtbar! Starte Serie...")
                        cdp_click(driver, btn)
                        time.sleep(5)
                        found_new_series = True
                        break
                    else:
                        print(f"   -> Start-Button {index + 1} hat keinen Stern, ist aber aktuell unsichtbar.")
            
            if not found_new_series:
                print("Keine offenen Aufgaben mehr gefunden! Beende Bot.")
                break

            # AUFGABEN SCHLEIFE
            for i in range(1, 30):
                print(f"\n--- Aufgabe {i} ---")
                driver.switch_to.default_content()
                try:
                    wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "seriesplayer")))
                except:
                    print("Kein seriesplayer gefunden, beende diese Serie.")
                    break
                
                sub_iframes = driver.find_elements(By.TAG_NAME, "iframe")
                if sub_iframes: driver.switch_to.frame(sub_iframes[0])
                
                # KURZE WARTEZEIT FÜR ELEMENT-LADEN (Wichtig für Modus-Erkennung!)
                time.sleep(2)

                # Screenshot & Lösung
                img_path = f"task_{i}.png"
                driver.save_screenshot(img_path)
                # --- KI LÖSUNG HOLEN ---
                print("   KI analysiert Bild...")
                loesung = solve_with_ai(img_path)
                
                if not loesung:
                    print("   KI konnte keine Lösung finden oder es gab einen Fehler.")
                    # Hier könnte man entscheiden, ob man die Serie abbricht oder die Aufgabe überspringt
                    continue # Versuche die nächste Aufgabe in der Serie
                print(f"   KI-Lösung: '{loesung}'")

                # PRÜFE MODUS
                options = driver.find_elements(By.CSS_SELECTOR, "label, [role='radio'], [class*='OptionDecorator__button']")
                drag_items = driver.find_elements(By.CSS_SELECTOR, "[data-rfd-draggable-id], [class*='DragSourceGizmo'], [id^='drag-source'], [id^='dnd-frame'], [class*='drag-source']")
                drop_targets = driver.find_elements(By.CSS_SELECTOR, "[data-droptarget], [data-cy*='drop-target'], [class*='DropTargetGizmo'], [id^='drop-target'], [class*='drop-target']")
                geo_point_tools = driver.find_elements(By.XPATH, "//*[local-name()='use' and contains(@href, 'add-point')]")
                geo_segment_tools = driver.find_elements(By.XPATH, "//*[local-name()='use' and contains(@href, 'add-segment')]")
                
                if geo_point_tools:
                    # MODUS: Geometrie (Interaktives Zeichnen)
                    print("   MODUS: Geometrie Graphenzeichner erkannt! Berechne SVG Pixel-Koordinaten...")
                    
                    # Tool-Buttons können im SVG selbst oder in einem Button liegen. Wir suchen den klickbaren Parent.
                    point_tool = driver.find_element(By.XPATH, "//*[local-name()='use' and contains(@href, 'add-point')]/ancestor::button[1] | //*[local-name()='use' and contains(@href, 'add-point')]/..")
                    segment_tool = None
                    if geo_segment_tools:
                        segment_tool = driver.find_element(By.XPATH, "//*[local-name()='use' and contains(@href, 'add-segment')]/ancestor::button[1] | //*[local-name()='use' and contains(@href, 'add-segment')]/..")
                    
                    # 1. Pixel-Skalierung aus dem SVG extrahieren
                    mapping = driver.execute_script("""
                        let texts = Array.from(document.querySelectorAll("svg text")).map(t => {
                            let text = t.textContent.trim();
                            let num = parseFloat(text.replace(',', '.'));
                            if (isNaN(num)) return null;
                            let rect = t.getBoundingClientRect();
                            return { val: num, x: rect.left + rect.width/2, y: rect.top + rect.height/2 };
                        }).filter(t => t !== null);
                        if (texts.length < 3) return null;

                        let xAxisTexts = [];
                        let yAxisTexts = [];
                        for (let t of texts) {
                            let sameY = texts.filter(o => Math.abs(o.y - t.y) < 15);
                            if (sameY.length > xAxisTexts.length) xAxisTexts = sameY;
                            let sameX = texts.filter(o => Math.abs(o.x - t.x) < 25);
                            if (sameX.length > yAxisTexts.length) yAxisTexts = sameX;
                        }

                        xAxisTexts.sort((a,b) => a.val - b.val);
                        yAxisTexts.sort((a,b) => a.val - b.val);
                        if (xAxisTexts.length < 2 || yAxisTexts.length < 2) return null;

                        return {
                            ppuX: (xAxisTexts[xAxisTexts.length-1].x - xAxisTexts[0].x) / (xAxisTexts[xAxisTexts.length-1].val - xAxisTexts[0].val),
                            ppuY: (yAxisTexts[yAxisTexts.length-1].y - yAxisTexts[0].y) / (yAxisTexts[yAxisTexts.length-1].val - yAxisTexts[0].val),
                            refX: xAxisTexts[0],
                            refY: yAxisTexts[0]
                        };
                    """)
                    
                    if not mapping:
                        print("   Fehler: Konnte Koordinatesystem-Skalierung im SVG nicht ausmessen!")
                    else:
                        print(f"      SVG Mapping erfolgreich: X-Skala={mapping['ppuX']:.2f}px pro Einheit, Y-Skala={mapping['ppuY']:.2f}px")
                        
                        target_lines = [line.strip() for line in loesung.split('\\n') if ',' in line]
                        parsed_points = []
                        for line in target_lines:
                            parts = line.split(',')
                            if len(parts) == 2:
                                try:
                                    parsed_points.append((float(parts[0].strip()), float(parts[1].strip())))
                                except: pass
                        
                        print(f"      Gefundene mathematische Punkte: {parsed_points}")
                        
                        pixel_coords = []
                        for mx, my in parsed_points:
                            px = mapping['refX']['x'] + (mx - mapping['refX']['val']) * mapping['ppuX']
                            py = mapping['refY']['y'] + (my - mapping['refY']['val']) * mapping['ppuY']
                            pixel_coords.append((px, py))
                        
                        # Setze Punkte
                        if pixel_coords:
                            print("      Klicke Punkte auf dem Graphen...")
                            try: cdp_click(driver, point_tool)
                            except: ActionChains(driver).click(point_tool).perform()
                            time.sleep(1)
                            
                            for px, py in pixel_coords:
                                cdp_click_coord(driver, px, py)
                                time.sleep(0.5)
                            
                            # Verbinde Punkte mit Strecken
                            if segment_tool and len(pixel_coords) > 1:
                                print("      Zeichne Verbindungsstrecken...")
                                try: cdp_click(driver, segment_tool)
                                except: ActionChains(driver).click(segment_tool).perform()
                                time.sleep(1)
                                
                                for i in range(len(pixel_coords) - 1):
                                    cdp_click_coord(driver, pixel_coords[i][0], pixel_coords[i][1])
                                    time.sleep(0.3)
                                    cdp_click_coord(driver, pixel_coords[i+1][0], pixel_coords[i+1][1])
                                    time.sleep(0.5)
                            print("      Zeichnen abgeschlossen!")
                            
                elif drop_targets and len(drop_targets) >= 1 and drag_items:
                    # MODUS: Element-Zuordnung (Lücken)
                    print("   MODUS: Zuordnung-Aufgabe (Lücken) erkannt. Ziehe Elemente an Position...")
                    target_lines = [line.strip().lower() for line in loesung.split('\n') if line.strip()]
                    
                    # Sortiere Ziele visuell (Lese-Reihenfolge: erst Y, dann X)
                    targets_sorted = sorted(drop_targets, key=lambda t: (t.location['y'] // 15, t.location['x']))
                    
                    for i, target_text in enumerate(target_lines):
                        if i >= len(targets_sorted): break
                        
                        target_elem = targets_sorted[i]
                        
                        # Wir suchen das beste match in den verbleibenden draggable Elementen,
                        # da alte Elemente DOM-stale sein könnten, wenn sie gedropped wurden!
                        current_drag_items = driver.find_elements(By.CSS_SELECTOR, "[data-rfd-draggable-id], [class*='DragSourceGizmo'], [id^='drag-source'], [id^='dnd-frame'], [class*='drag-source']")
                        
                        best_match_idx = -1
                        best_ratio = 0
                        for curr_idx, curr_item in enumerate(current_drag_items):
                            # Nur Elemente, die wirklich Text haben oder Kindelemente mit Text
                            curr_text = curr_item.text.replace("\n", " ").strip()
                            if not curr_text or len(curr_text) < 1:
                                # Suche tiefer (z.B. in MathML oder Formularen)
                                try: 
                                    child_with_text = curr_item.find_element(By.XPATH, ".//*[normalize-space(text())]")
                                    curr_text = child_with_text.text.replace("\n", " ").strip()
                                except: pass
                            
                            val_norm = normalize_chars(target_text)
                            c_norm = normalize_chars(curr_text)
                            
                            ratio = difflib.SequenceMatcher(None, val_norm, c_norm).ratio()
                            if val_norm in c_norm or c_norm in val_norm:
                                ratio = max(ratio, 0.9)
                            
                            if ratio > best_ratio and ratio > 0.4:
                                # Priorisiere Elemente außerhalb der Lücken
                                for dt in drop_targets:
                                    if abs(dt.location['x'] - curr_item.location['x']) < 15 and abs(dt.location['y'] - curr_item.location['y']) < 15:
                                        ratio -= 0.1
                                
                                if ratio > best_ratio:
                                    best_ratio = ratio
                                    best_match_idx = curr_idx
                                
                        if best_match_idx != -1:
                            source_elem = current_drag_items[best_match_idx]
                            print(f"      Ziehe Element '{target_text[:20]}...' in Lücke {i+1} (Match: {best_ratio*100:.0f}%)")
                            
                            # Sanftes Drag and Drop um React DOM Tracker nicht zu brechen
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", source_elem)
                            time.sleep(0.3)
                            ActionChains(driver).click_and_hold(source_elem).pause(0.5).move_to_element(target_elem).pause(0.5).release().perform()
                            time.sleep(1) # React Animation abwarten
                        else:
                            print(f"      Warnung: Kein passendes Element für Lücke {i+1} ('{target_text[:30]}...') gefunden!")
                            
                elif drag_items and len(drag_items) > 1:
                    # MODUS: Drag and Drop (Sortieren)
                    print("   MODUS: Sortier-Aufgabe erkannt. Sortiere Elemente...")
                    target_lines = [line.strip().lower() for line in loesung.split('\n') if line.strip()]
                    
                    for i in range(len(target_lines)):
                        target_text = target_lines[i]
                        
                    # DOM laufend neu abfragen
                    dnd_selector = "[data-rfd-draggable-id], [class*='DragSourceGizmo'], [id^='drag-source'], [id^='dnd-frame']"
                    current_items = driver.find_elements(By.CSS_SELECTOR, dnd_selector)
                    
                    # Erstelle eine Liste von Dictionaries, die Element und Text enthalten, sortiert nach Y-Koordinate
                    items_with_y = []
                    for item in current_items:
                        items_with_y.append({
                            'elem': item,
                            'text': item.text.replace("\n", " ").strip().lower(),
                            'y': item.location['y']
                        })
                    items_with_y.sort(key=lambda x: x['y'])
                    current_texts = [item['text'] for item in items_with_y]

                    # Finde die Ziel-Reihenfolge der aktuellen Elemente
                    # Wir lassen uns von der KI leiten.
                    for target_idx, target_text in enumerate(target_lines):
                        # Finde das Element, das dem target_text am ähnlichsten ist
                        # Robustere Methode mit difflib statt einfachem 'in'
                        best_match_idx = -1
                        best_ratio = 0
                        for curr_idx, curr_text in enumerate(current_texts):
                            ratio = difflib.SequenceMatcher(None, target_text, curr_text).ratio()
                            # Auch einfacher Substring-Check als Backup
                            if target_text in curr_text or curr_text in target_text:
                                ratio = max(ratio, 0.9)
                                
                            if ratio > best_ratio and ratio > 0.4:
                                best_ratio = ratio
                                best_match_idx = curr_idx
                                
                        if best_match_idx == -1:
                            print(f"      Warnung: Konnte den KI-Text '{target_text[:30]}...' keinem Element zuordnen!")
                            continue
                            
                        if best_match_idx != target_idx:
                            print(f"      Verschiebe von Platz {best_match_idx+1} auf Platz {target_idx+1} (Match: {best_ratio*100:.0f}%)")
                            # Move element from best_match_idx to target_idx
                            source_item = items_with_y[best_match_idx]['elem']
                            
                            # Klicke auf das Handle zum Fokussieren und erzwinge Fokus
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", source_item)
                            time.sleep(0.3)
                            driver.execute_script("arguments[0].focus();", source_item)
                            time.sleep(0.2)
                            
                            # Echter Klick zum Aktivieren
                            cdp_click(driver, source_item)
                            time.sleep(0.3)
                            
                            # SPACE um das Element "aufzuheben"
                            ActionChains(driver).send_keys_to_element(source_item, Keys.SPACE).perform()
                            time.sleep(1.2)
                            
                            # Berechne Differenz
                            diff = target_idx - best_match_idx
                            
                            # Bewege mit Pfeiltasten
                            if diff > 0:
                                for _ in range(diff):
                                    ActionChains(driver).send_keys(Keys.ARROW_DOWN).perform()
                                    time.sleep(0.4)
                            elif diff < 0:
                                for _ in range(abs(diff)):
                                    ActionChains(driver).send_keys(Keys.ARROW_UP).perform()
                                    time.sleep(0.4)
                                    
                            # SPACE um es fallen zu lassen
                            ActionChains(driver).send_keys(Keys.SPACE).perform()
                            time.sleep(1.5) # Warten auf React Render/Animation
                            
                            # Update die interne Liste: Element wandert von best_match_idx nach target_idx
                            moved_item = items_with_y.pop(best_match_idx)
                            items_with_y.insert(target_idx, moved_item)
                            current_texts = [item['text'] for item in items_with_y]
                        else:
                            print(f"      Platz {target_idx+1} ist bereits korrekt: '{target_text[:30]}...'")
                            
                elif options and len(options) > 1:
                    # MODUS: Multiple Choice
                    clicked = False
                    for opt in options:
                        opt_text = opt.text.strip().lower()
                        if not opt_text: continue
                        if opt_text in loesung.lower() or loesung.lower() in opt_text:
                            print(f"   Option '{opt.text.strip()}' ausgewählt")
                            cdp_click(driver, opt)
                            clicked = True
                            break
                    if not clicked:
                        print("   Warnung: Keine exakt passende Multiple-Choice-Option gefunden!")
                else:
                    # MODUS: Eingabefelder / Dropdowns
                    print("   MODUS: Eingabefelder / Dropdowns erkannt...")
                    
                    interactives = driver.find_elements(By.CSS_SELECTOR, "[role='textbox'], [data-testid='dropdown-button'], [class*='Dropdown__dropdown']")
                    
                    # Elemente deduplizieren (falls role='textbox' und data-testid='cursor' übereinanderliegen)
                    unique_interactives = []
                    for el in interactives:
                        if not el.is_displayed(): continue
                        loc = el.location
                        is_dupe = False
                        for u in unique_interactives:
                            if abs(u.location['x'] - loc['x']) < 15 and abs(u.location['y'] - loc['y']) < 15:
                                is_dupe = True
                                break
                        if not is_dupe:
                            unique_interactives.append(el)
                    
                    # Sortieren der Felder von links nach rechts (Y // 30 = grobe Zeilen, dann X)
                    unique_interactives.sort(key=lambda e: (e.location['y'] // 30, e.location['x']))
                    
                    target_lines = [line.strip() for line in loesung.split('\n') if line.strip()]
                    
                    # SMART EINGABE FILTER FÜR EXPONENTEN (Nur wenn es wirklich nur 1 Feld ist)
                    if len(unique_interactives) == 1 and len(target_lines) >= 1 and '^' in target_lines[0]:
                        try:
                            cdp_click(driver, unique_interactives[0])
                            time.sleep(0.5)
                            driver.find_element(By.CSS_SELECTOR, "[data-cy='keyboard-exponent']")
                        except:
                            print("   Info: '^'-Taste fehlt auf der Tastatur. Offenbar ist nur der Exponent gesucht!")
                            target_lines[0] = target_lines[0].split('^')[-1].strip()
                            print(f"   Angepasste Lösung: '{target_lines[0]}'")

                    # Sequentielles Ausfüllen der Felder 
                    for idx, el in enumerate(unique_interactives):
                        if idx >= len(target_lines):
                            print(f"   Warnung: Mehr Felder ({len(unique_interactives)}) als Lösungszeilen ({len(target_lines)}) gefunden. Beende Eingabe.")
                            break
                        
                        val = target_lines[idx]
                        el_class = el.get_attribute("class") or ""
                        el_testid = el.get_attribute("data-testid") or ""
                        
                        if "Dropdown" in el_class or "dropdown" in el_testid.lower():
                            print(f"      Dropdown erkannt. Wähle '{val}' aus...")
                            cdp_click(driver, el)
                            clicked_opt = False
                            # Versuche die Option zu finden - wir suchen im gesamten DOM, da sie oft in Portals liegen
                            time.sleep(1.0)
                            
                            val_norm = normalize_chars(val)
                            
                            # Suche gezielter nach typischen Dropdown-Optionen. 
                            # 'question' ist oft ein Parent-Label, wir suchen nur tiefe Kinder!
                            potential_options = driver.find_elements(By.CSS_SELECTOR, "[class*='Option'], [role='menuitem'], [data-cy*='option'], [class*='DropdownOption']")
                            
                            best_opt = None
                            max_ratio = 0
                            
                            for opt in potential_options:
                                try:
                                    if not opt.is_displayed(): continue
                                    
                                    # Hole Text und Attribute für Match
                                    txt = opt.text.strip()
                                    test_id = opt.get_attribute("data-testid") or ""
                                    cy_id = opt.get_attribute("data-cy") or ""
                                    
                                    # Wenn kein Text da ist (z.B. reines Symbol-Bild), nutze test-id
                                    match_candidates = [txt, test_id, cy_id]
                                    
                                    for candidate in match_candidates:
                                        if not candidate: continue
                                        c_norm = normalize_chars(candidate)
                                        
                                        # Ratio berechnen
                                        ratio = difflib.SequenceMatcher(None, val_norm, c_norm).ratio()
                                        if val_norm in c_norm or c_norm in val_norm:
                                            # Substring-Match ist gut (0.85), aber nicht perfekt
                                            ratio = max(ratio, 0.85)
                                        
                                        # EXAKTER TREFFER (PRIO 1)
                                        if val_norm == c_norm:
                                            ratio = 2.0 # Win everything
                                        
                                        # BESTRAFUNG FÜR LÄNGENUNTERSCHIED
                                        len_diff = abs(len(val_norm) - len(c_norm))
                                        if len_diff > 0:
                                            ratio -= min(0.3, len_diff * 0.05)
                                            
                                        if ratio > max_ratio and ratio > 0.4:
                                            max_ratio = ratio
                                            best_opt = opt
                                except: continue
                                
                            if best_opt and max_ratio > 0.6:
                                print(f"      Option gefunden: '{best_opt.text.strip() or 'Symbol'}' (Match: {max_ratio*100:.0f}%)")
                                cdp_click(driver, best_opt)
                                time.sleep(0.5)
                                clicked_opt = True
                            
                            if not clicked_opt:
                                # Letzter Verzweiflungs-Versuch per direktem XPath-Match (strikt)
                                # Wir probieren verschiedene Minus-Zeichen durch
                                for m_char in ["-", "–", "−"]:
                                    lookup = val.replace("-", m_char)
                                    try:
                                        hard_opt = driver.find_element(By.XPATH, f"//*[normalize-space(text())='{lookup}' or contains(@data-testid, '{lookup}')]")
                                        if hard_opt.is_displayed():
                                            cdp_click(driver, hard_opt)
                                            time.sleep(0.3)
                                            clicked_opt = True
                                            break
                                    except: pass
                                
                            if not clicked_opt:
                                print(f"      Fehler: Dropdown-Option '{val}' nicht sichtbar gefunden!")
                        else:
                            print(f"      Textfeld erkannt. Tippe '{val}' ein...")
                            cdp_click(driver, el)
                            time.sleep(0.5)
                            for char in val:
                                if char in KEYBOARD_MAP:
                                    key_id = KEYBOARD_MAP[char]
                                    try:
                                        key_btn = driver.find_element(By.CSS_SELECTOR, f"[data-cy='{key_id}']")
                                        cdp_click(driver, key_btn)
                                        time.sleep(0.3)
                                    except:
                                        print(f"      Taste '{char}' nicht auf der Tastatur gefunden!")

                # ABSCHICKEN & WEITER
                print("   Sende ab...")
                try:
                    submit = wait.until(EC.element_to_be_clickable((By.ID, "submit-btn")))
                    cdp_click(driver, submit)
                    time.sleep(2)
                    
                    found_action = False
                    for _ in range(10):
                        results_btns = driver.find_elements(By.ID, "results-btn")
                        if results_btns and results_btns[0].is_displayed():
                            print("   Letzte Aufgabe erreicht! Klicke 'Ergebnis anzeigen'...")
                            cdp_click(driver, results_btns[0])
                            found_action = 'results'
                            time.sleep(3)
                            break
                        
                        next_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Aufgabe') or contains(., 'Weiter')]")
                        if next_btns and next_btns[0].is_displayed():
                            cdp_click(driver, next_btns[0])
                            found_action = 'next'
                            time.sleep(3)
                            break
                        
                        time.sleep(1)
                    
                    if found_action == 'results':
                        break  # Serie beendet
                    elif not found_action:
                        print("   Weder 'Weiter' noch 'Ergebnis anzeigen' gefunden.")
                        break
                        
                except Exception as e:
                    print(f"   Fehler beim Abschicken: {e}")
                    break
                    
            # NACH DER SERIE (OK KLICKEN)
            print("Warte auf 'OK' Button...")
            driver.switch_to.default_content()
            try:
                ok_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[text()='OK']")))
                cdp_click(driver, ok_btn)
                print("OK geklickt.")
                time.sleep(3)
            except:
                try:
                    driver.switch_to.frame("seriesplayer")
                    ok_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[text()='OK']")))
                    cdp_click(driver, ok_btn)
                    print("OK im Frame geklickt.")
                    time.sleep(3)
                except:
                    print("Kein OK-Button gefunden, fahre fort...")

    finally:
        print("Bot beendet.")
        driver.quit()

if __name__ == "__main__":
    run_bot()