import os
import time
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()
USER = os.getenv("SP_USERNAME")
PASS = os.getenv("SP_PASSWORD")

options = Options()
options.add_argument("--headless")
options.add_argument("--window-size=1920,1080")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=options)
wait = WebDriverWait(driver, 20)

try:
    print(f"Login im Schulportal ({USER})...")
    driver.get("https://schulportal.berlin.de/start")
    wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "swift_cn_login"))).click()
    wait.until(EC.presence_of_element_located((By.ID, "username"))).send_keys(USER)
    driver.find_element(By.ID, "password").send_keys(PASS)
    driver.find_element(By.ID, "kc-login").click()
    print("Login success.")

    print("Öffne Bettermarks...")
    bm_icon = wait.until(EC.element_to_be_clickable((By.XPATH, "//img[@title='bettermarks']")))
    driver.execute_script("arguments[0].click();", bm_icon)
    time.sleep(2)
    driver.switch_to.window(driver.window_handles[-1])
    
    time.sleep(5)
    
    print("Suche Start-Button...")
    try:
        start_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-cy='ActionButton-start']")))
        driver.execute_script("arguments[0].click();", start_btn)
        time.sleep(5)
    except:
        print("Start-Button nicht gefunden, möglicherweise schon gestartet oder Selektor falsch.")
        
    print("Wechsle in Frame...")
    driver.switch_to.default_content()
    try:
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "seriesplayer")))
    except:
        print("Kein seriesplayer Frame.")
    
    sub_frames = driver.find_elements(By.TAG_NAME, "iframe")
    if sub_frames:
        print("Inneren Frame gefunden.")
        driver.switch_to.frame(sub_frames[0])
    
    print("Speichere DOM...")
    with open("bm_dom.html", "w") as f:
        f.write(driver.page_source)
    print("Erfolgreich gespeichert in bm_dom.html")
        
finally:
    driver.quit()
