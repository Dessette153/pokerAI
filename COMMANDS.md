# Poker AI - Komut Referansı

## Kurulum

```bash
pip install flask flask-socketio
```

---

## Web UI

```bash
python run_ui.py
# veya
python main.py ui
```

Tarayıcıda: **http://127.0.0.1:5000**

### UI Kontrolleri

| Element | Açıklama |
|---------|----------|
| **Opponent** seçici | Rakip tipi: `Simple` veya `Random` |
| **Showdown'da duraklat** | İşaretli → showdown'da sim durur, el incelenir |
| **Hız slider** (1x–Max) | Aksiyon gecikmesi: `1x`=1s, `5x`=0.2s, `Max`=0.05s |
| **▶ Start** | Simülasyonu başlat |
| **■ Stop** | Simülasyonu durdur |
| **[PREFLOP/FLOP/TURN/RIVER]** | Pause sırasında o streete revert et |
| **▶ Resume** | Pause'dan devam et |
| **▶▶ Next Hand** | Pause'dan çık, bir sonraki ele geç |

---

## Headless Batch Simülasyon

```bash
python main.py sim [SEÇENEKLER]
```

### Seçenekler

| Seçenek | Varsayılan | Açıklama |
|---------|-----------|----------|
| `--hands N` | 1000 | Simüle edilecek el sayısı |
| `--opponent` | `simple` | Rakip: `simple` veya `random` |
| `--mc-budget MS` | 50 | Monte Carlo zaman bütçesi (ms per karar) |
| `--no-log` | — | JSONL log dosyası yazma |

### Örnekler

```bash
# 1.000 el, Simple rakip, varsayılan MC (50ms)
python main.py sim

# 10.000 el, hızlı MC (20ms) → ~50 el/s, ~3 dakika
python main.py sim --hands 10000 --mc-budget 20

# 50.000 el, çok hızlı, log yok
python main.py sim --hands 50000 --mc-budget 10 --no-log

# Random rakibe karşı 5.000 el
python main.py sim --hands 5000 --opponent random

# Yüksek doğruluklu uzun simülasyon (yavaş, log ile)
python main.py sim --hands 10000 --mc-budget 200
```

### Hız Rehberi (mc-budget)

| `--mc-budget` | El/saniye (yaklaşık) | Kullanım |
|---------------|---------------------|----------|
| `10` | ~80 el/s | Sadece istatistik, düşük karar kalitesi |
| `20` | ~50 el/s | Hızlı benchmark |
| `50` | ~20 el/s | **Varsayılan** (iyi denge) |
| `100` | ~10 el/s | Daha doğru kararlar |
| `200` | ~5 el/s | Yüksek kalite |
| `900` | ~1 el/s | UI ile aynı kalite |

### Çıktı Formatı

```
=======================================================
  Poker AI - Batch Simulation
  AI v1  vs  Simple
  10,000 el  |  Stack: 10,000  |  Blinds: 50/100
=======================================================

    5.0%  El:    500  bb/100: +24.5  Net:    +1,225  Win%: 52.3%  48 el/s
   10.0%  El:  1,000  bb/100: +18.2  Net:    +1,820  Win%: 53.1%  49 el/s
   ...

=======================================================
  SONUÇLAR  (204s | 49 el/s)
=======================================================

  AI v1:
    bb/100  : +21.4
    Net     : +21,400
    Win%    : 53.2%
    VPIP    : 47.0%
    PFR     : 38.0%
    AF      : 2.1

  Simple:
    bb/100  : -21.4
    Net     : -21,400
    Win%    : 46.8%

  El istatistikleri:
    Fold    : 6,230 (62.3%)
    Showdown: 3,770 (37.7%)

  Log: logs/sim_10000hands_20260302_153012.jsonl
```

---

## Benchmark

AI v1'i hem Random hem Simple rakibe karşı arka arkaya test eder.

```bash
python main.py bench [SEÇENEKLER]
```

### Seçenekler

| Seçenek | Varsayılan | Açıklama |
|---------|-----------|----------|
| `--hands N` | 5000 | Her senaryo için el sayısı |
| `--mc-budget MS` | 50 | Monte Carlo bütçesi (ms) |

### Örnekler

```bash
# Hızlı benchmark (2 senaryo x 5.000 el)
python main.py bench

# Uzun ve doğru benchmark
python main.py bench --hands 10000 --mc-budget 100
```

---

## Smoke Test

Engine, evaluatör ve MC equity'yi hızlıca doğrular.

```bash
python main.py test
```

Beklenen çıktı:
```
  [OK] Evaluator
  [OK] Engine (10 el)
  [OK] Monte Carlo equity (AA preflop = 87.x%)
  [OK] AI v1 tier chart

  Tüm testler geçti.
```

---

## Log Dosyaları

Tüm batch simülasyon logları `logs/` klasörüne JSONL formatında yazılır.

```
logs/
  sim_10000hands_20260302_153012.jsonl   # main.py sim --hands 10000
  hands_20260302_153045.jsonl            # run_ui.py (UI session)
```

### Log Okuma

```bash
# Son 10 el olayını oku
python -c "
import json
with open('logs/sim_10000hands_....jsonl') as f:
    lines = f.readlines()
for line in lines[-20:]:
    ev = json.loads(line)
    if ev['event'] == 'hand_end':
        print(ev)
"

# Sadece showdown'ları filtrele
python -c "
import json
with open('logs/sim_...jsonl') as f:
    for line in f:
        ev = json.loads(line)
        if ev['event'] == 'showdown':
            print(ev)
"
```

### JSONL Event Tipleri

| Event | İçerik |
|-------|--------|
| `hand_start` | `hand_id`, `button_seat`, `stacks` |
| `deal_hole` | `hand_id`, `hole_cards` |
| `street_start` | `hand_id`, `street`, `pot`, `stacks` |
| `board_reveal` | `hand_id`, `street`, `board` |
| `action_taken` | `player`, `action`, `amount`, `pot_after`, `explanation` |
| `showdown` | `hole_cards`, `board`, `winner`, `scores` |
| `hand_end` | `winner`, `pot_won`, `was_fold`, `net_chips`, `final_stacks` |

---

## Config Parametreleri

`config.py` dosyasından düzenlenebilir:

```python
# Blindler ve stack
SB = 50
BB = 100
STARTING_STACK = 10_000

# Monte Carlo (UI için)
MC_TIME_BUDGET_MS = 900
MC_MIN_SAMPLES = 2_000
MC_MAX_SAMPLES = 20_000

# AI v1 strateji
MARGIN = 0.03          # call/fold equity marjı
OPEN_SIZE_BB = 2.5     # preflop açılış büyüklüğü (BB cinsinden)
BLUFF_RATE = 0.12      # bluff frekansı

# UI
UI_HOST = "127.0.0.1"
UI_PORT = 5000
```

---

## Uzun Simülasyon Önerileri

```bash
# 10.000 el (~3-4 dakika)
python main.py sim --hands 10000 --mc-budget 20 --no-log

# 50.000 el (~15 dakika, ciddi istatistik)
python main.py sim --hands 50000 --mc-budget 10 --no-log

# Arka planda çalıştır (Windows)
start /B python main.py sim --hands 100000 --mc-budget 10 --no-log > sim_output.txt

# Arka planda çalıştır (Linux/Mac)
nohup python main.py sim --hands 100000 --mc-budget 10 --no-log > sim_output.txt &
```
