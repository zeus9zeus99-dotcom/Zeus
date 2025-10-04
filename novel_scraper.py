import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# --- الإعدادات ---
NOVEL_URL = "https://www.webnovel.com/book/beast-taming-the-more-the-better_29379860808949905"
OUTPUT_FOLDER = "novel_chapters"
# يمكن تحديد عدد الفصول التي تريد سحبها (للتجربة )
# اضبطه على None لسحب كل الفصول
CHAPTER_LIMIT = 5 

def setup_driver():
    """إعداد متصفح Chrome للعمل في بيئة Codespace."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # تشغيل المتصفح في الخلفية بدون واجهة رسومية
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # لا حاجة لتحديد مسار WebDriver إذا كان مثبتًا بشكل صحيح
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def get_chapter_links(driver, url):
    """الحصول على قائمة روابط الفصول من صفحة الرواية الرئيسية."""
    print("⏳ جاري زيارة صفحة الرواية الرئيسية وجمع روابط الفصول...")
    driver.get(url)
    time.sleep(5)  # انتظر 5 ثوانٍ للسماح للصفحة بالتحميل

    # العثور على كل الروابط التي تؤدي إلى الفصول
    # بناءً على تحليل الموقع، الروابط موجودة داخل عناصر <a> مع فئة 'j_chap-item'
    chapter_elements = driver.find_elements(By.CSS_SELECTOR, "a.j_chap-item")
    
    links = [elem.get_attribute('href') for elem in chapter_elements if elem.get_attribute('href')]
    
    if not links:
        print("❌ لم يتم العثور على روابط فصول. قد يكون تصميم الموقع قد تغير.")
        return []
        
    print(f"✅ تم العثور على {len(links)} رابط فصل.")
    return links

def scrape_chapter(driver, url):
    """سحب عنوان ونص الفصل من رابط معين."""
    print(f"   - جاري سحب الفصل من: {url}")
    driver.get(url)
    time.sleep(3) # انتظر لتحميل محتوى الفصل

    try:
        # استخراج عنوان الفصل
        title_element = driver.find_element(By.CSS_SELECTOR, "h2.j_chap-title")
        title = title_element.text.strip()
    except:
        title = "Untitled Chapter"

    # استخراج نص الفصل
    # النص موجود داخل عناصر <p> داخل حاوية الفصل الرئيسية
    paragraphs = driver.find_elements(By.CSS_SELECTOR, "div.j_readContent p")
    content = "\n".join([p.text for p in paragraphs])
    
    return title, content

def main():
    driver = setup_driver()
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    chapter_links = get_chapter_links(driver, NOVEL_URL)

    if chapter_links:
        # تحديد عدد الفصول للسحب
        links_to_scrape = chapter_links[:CHAPTER_LIMIT] if CHAPTER_LIMIT else chapter_links
        print(f"\n🚀 ستبدأ عملية سحب {len(links_to_scrape)} فصل...\n")

        for i, link in enumerate(links_to_scrape):
            title, content = scrape_chapter(driver, link)
            
            # تنظيف اسم الملف من الأحرف غير الصالحة
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '.')).rstrip()
            filename = f"{i+1:04d} - {safe_title}.txt"
            filepath = os.path.join(OUTPUT_FOLDER, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"العنوان: {title}\n\n")
                f.write(content)
            
            print(f"   ✅ تم حفظ الفصل في: {filepath}")

    driver.quit()
    print("\n🎉🎉🎉 اكتملت عملية سحب الفصول بنجاح! 🎉🎉🎉")

if __name__ == "__main__":
    main()
