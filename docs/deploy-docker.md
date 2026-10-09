# تشغيل البوت على VPS بـ Docker (مثال: Hostinger KVM 2)

البوت ما بيحتاج أي بورت مفتوح. هو بس بيتصل بباينانس، وسيرفر KVM 2 كافي وزيادة.

## 0) قبل ما تبلّش: موقع السيرفر مهم ⚠️
باينانس **بيحجب السيرفرات الموجودة بأمريكا**: بيرجّع خطأ `451`. لما تنشئ الـ VPS بـ hPanel اختار داتا سنتر **برّا أمريكا**، مثلاً أوروبا (ألمانيا، فرنسا، ليتوانيا، بريطانيا) أو آسيا.

نظام التشغيل: **Ubuntu 24.04**. إذا Hostinger عارضة قالب "Ubuntu with Docker" اختاره، وبتقدر تتخطى الخطوة 2.

## 1) ادخل على السيرفر
من hPanel ← VPS خذ الـ IP وكلمة سر الـ root، وبعدين من جهازك:
```bash
ssh root@IP_السيرفر
```

## 2) ثبّت Docker (مرة وحدة)
```bash
curl -fsSL https://get.docker.com | sh
docker --version && docker compose version
```

تأكد إنه السيرفر بيقدر يوصل لباينانس:
```bash
curl -s https://api.binance.com/api/v3/ping
```
لازم يطلعلك `{}`. إذا طلعلك خطأ 451 أو "restricted location"، يا إما تغيّر موقع السيرفر، يا إما تجرّب:
```bash
curl -s "https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT"
```
إذا هاد اشتغل، حط بملف `config.yaml`: `market_data_url: https://data-api.binance.vision`. هيك بيشتغل الـ paper والـ backtest، بس الـ live بيحتاج سيرفر بموقع مسموح.

## 3) نزّل المشروع
```bash
cd ~
git clone https://github.com/karmontal/BinanceBot.git
cd BinanceBot
git checkout main        # أو ccr-28b37f9d-egaxwx إذا لسا ما عملت Merge
```
> إذا الريبو Private بيطلب منك username وpassword. الـ password لازم يكون **Personal Access Token** من GitHub (Settings ← Developer settings ← Tokens)، مش كلمة سر حسابك.

## 4) جرّب باك تست (اختياري بس منصوح فيه)
```bash
docker compose build
docker compose run --rm bot python main.py backtest --days 180
```
النتائج بتنحفظ بمجلد `reports/` على السيرفر.

## 5) شغّل البوتات 24/7
```bash
docker compose up -d --build
```
- `-d` يعني بيشتغل بالخلفية. فيك تسكّر الـ SSH وبيضل شغّال.
- `restart: unless-stopped` يعني إذا وقع أو السيرفر عمل restart، بيرجع يشتغل لحاله.
- كل البيانات بمجلد `data/` على السيرفر، فما بتضيع إذا عملت rebuild للكونتينر.

## الأوامر اليومية

| بدك | الأمر |
|---|---|
| تشوف الـ logs مباشرة | `docker compose logs -f --tail 100` (اطلع بـ `Ctrl+C`، البوت بيضل شغّال) |
| جدول المقارنة هلأ | `docker compose exec bot python main.py report` |
| تحفظ التقرير CSV | `docker compose exec bot python main.py report --csv reports/week1.csv` |
| تتأكد إنه شغّال | `docker compose ps` |
| توقّفه | `docker compose stop` |
| تشغّله | `docker compose start` |
| تعدّل الإعدادات | `nano config.yaml` وبعدين `docker compose restart` |
| تحدّث الكود | `git pull && docker compose up -d --build` |

### تصفير البوتات (بداية من الصفر)
```bash
docker compose down
rm data/bots.db
docker compose up -d
```
لتصفير بوت واحد، أو بعد ما تغيّر استراتيجية بوت موجود:
```bash
docker compose down
docker compose run --rm bot python main.py run --reset اسم_البوت
# رح يشتغل قدامك: استنى ثواني لحد ما تشوف "bots running"، وبعدين Ctrl+C
docker compose up -d
```

### نسخة احتياطية من النتائج على جهازك
من جهازك (مش من السيرفر):
```bash
scp root@IP_السيرفر:~/BinanceBot/data/bots.db .
scp -r root@IP_السيرفر:~/BinanceBot/reports .
```

## لاحقاً: Testnet / Live
```bash
cp .env.example .env
nano .env          # حط المفاتيح
chmod 600 .env
nano config.yaml   # غيّر mode للبوت اللي بدك ياه
docker compose up -d
```
- ملف `.env` ما بينرفع على GitHub (موجود بـ `.gitignore`)، ولا بينحط جوّا الـ image.
- بمفتاح الـ API على باينانس: فعّل **IP whitelist** وحط IP السيرفر، وفعّل Spot Trading بس، و**لا تفعّل Withdrawals**.

## حماية السيرفر (منصوح فيها)
```bash
ufw allow OpenSSH
ufw enable
apt update && apt upgrade -y
```
البوت ما بيحتاج أي بورت ثاني. والأفضل كمان تدخل بـ SSH key بدل كلمة السر.
