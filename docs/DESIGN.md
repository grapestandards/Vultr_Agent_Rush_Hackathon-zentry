# Zentry — Solution Design

Nov 4, 2026 · @Kiwi · rev. Nov 7, 2026 (web เปลี่ยนจาก Next.js เป็น SvelteKit, เพิ่ม UI style guide, จำนวนเงินใช้คอลัมน์ `*_satang`)

## ภาพรวม

Zentry คือแพลตฟอร์ม Financial Crime & Payment Ops สำหรับ e-wallet, ผู้ให้บริการชำระเงิน และธนาคารดิจิทัลในไทย ทำงานครบ 4 อย่างในระบบเดียว: จับบัญชีม้าและธุรกรรมผิดปกติ, กระทบยอดธุรกรรม, ติดตามการชำระเงินที่ค้าง และให้ทีมปรับจูนโมเดลตรวจจับได้เองจากหน้าเว็บ โดยทั้งหมดรันบน Vultr

**ปัญหา:** บัญชีม้าและแก๊งคอลเซ็นเตอร์ทำให้เงินผู้เสียหายถูกโอนต่อหลายทอดภายในไม่กี่นาที ทีม compliance เจอ alert ท่วมและ false positive สูง ส่วนทีม finance ยังกระทบยอดกับ statement ด้วย Excel และตามยอดค้างด้วยมือ

**ผู้ใช้หลัก**

| บทบาท | ใช้ระบบทำอะไร |
| --- | --- |
| AML / Fraud Analyst | ดู alert, เปิดเคส, ดูกราฟเส้นทางเงิน, อนุมัติร่าง STR |
| Finance Ops | กระทบยอดธุรกรรมกับ settlement และ statement ธนาคาร, ปิดรายการค้าง |
| Collections Officer | ติดตามยอดค้างชำระและ chargeback, ส่งข้อความเตือน |
| Compliance Manager / Model Owner | ปรับ scenario, เทรนและเทียบโมเดลรุ่นใหม่, อนุมัติก่อนขึ้น production |

**หลักการออกแบบ**

- AI ตั้งธงและสืบสวน แต่การระงับบัญชี การส่งรายงาน และการขึ้นโมเดลใหม่ ต้องให้คนกดอนุมัติทุกครั้ง
- ทุกการตัดสินใจของ AI มีเหตุผลและหลักฐานเก็บไว้ใน audit log
- ใช้ข้อมูลสังเคราะห์ทั้งหมด ไม่อ้างว่าเชื่อมกับ ปปง. หรือธนาคารจริง
- **เรื่อง "tune model":** งานนี้ไม่มี Vultr GPU ให้ใช้ เราจึงไม่ fine-tune LLM แต่จะเทรนโมเดล ML ตรวจจับบน CPU ของ Vultr VM จาก label ที่ analyst ให้ แล้วปรับ LLM agent ผ่าน prompt, ตัวอย่าง few-shot และคลังความรู้ RAG ใน Vultr Vector Store แทน (รายละเอียดอยู่ในหัวข้อ Model Tuning Studio)

## โมดูลหลัก

ระบบมี 6 โมดูล ทุกโมดูลส่งงานเข้า Case Manager กลางตัวเดียว เคสจากการกระทบยอด การติดตามหนี้ และ fraud จึงเชื่อมกันได้

### 1. Flag Anomalies (Transaction Monitoring)

ตรวจทุกธุรกรรมที่ไหลเข้ามาด้วย 3 ชั้น แล้วรวมเป็นคะแนนความเสี่ยง 0–100

- **กฎ (Scenarios):** เงินเข้าแล้วออกเร็ว (pass-through), fan-in / fan-out, บัญชีเงียบที่กลับมาเคลื่อนไหว, การแตกยอด (structuring), บัญชีเปิดใหม่แต่รับเงินจากคนแปลกหน้าจำนวนมาก
- **โมเดล ML:** LightGBM ให้คะแนนแต่ละธุรกรรมจาก feature เช่น อายุบัญชี, เวลาที่เงินค้างในบัญชี, จำนวนคู่โอนใหม่ต่อวัน, อัตราส่วนเงินออกต่อเงินเข้า พร้อม Isolation Forest จับความผิดปกติที่ยังไม่มี label
- **Graph features:** degree, PageRank และกลุ่มบัญชีที่เชื่อมกัน (Louvain community) คำนวณด้วย NetworkX ใน worker แล้วส่งเข้าโมเดล

ผลลัพธ์คือ alert ที่บอกได้เสมอว่ากฎไหนทำงาน และ feature ไหนดันคะแนนขึ้น (SHAP top 3)

### 2. AI Investigator (สืบสวนและจัดลำดับ alert)

LLM agent บน Vultr Serverless Inference เรียก tool ของระบบเราเอง (ดึงประวัติบัญชี, ขยายกราฟ N hop, เทียบชื่อกับ watchlist, ค้น typology ใน RAG) แล้วสรุปเป็นแฟ้มเคส: เกิดอะไร, เข้ารูปแบบไหน, บัญชีไหนเกี่ยวข้อง, ความเสี่ยงระดับไหน และแนะนำให้ทำอะไรต่อ (ปิด / ยกระดับ / แนะนำระงับ) พร้อมร่าง STR ให้ analyst แก้ไข

### 3. Transaction Graph Explorer

หน้าดูกราฟเส้นทางเงินแบบ interactive ทำด้วย Cytoscape.js

- node = บัญชี (สีตามคะแนนความเสี่ยง, ขนาดตามยอดเงินที่ผ่าน), edge = การโอน (หนาตามยอด, ลูกศรตามทิศทาง)
- คลิกบัญชีเพื่อขยายทีละ hop, เลื่อน time slider เพื่อ replay ว่าเงินไหลไปทางไหนทีละนาที
- ปุ่ม "Trace from victim" ไฮไลต์เส้นทางจากบัญชีผู้เสียหายไปถึงบัญชีปลายทาง และคำนวณว่าเงินยังค้างอยู่ที่ไหนเท่าไหร่ (ใช้ต่อกับ Payment Follow-ups)
- กลุ่มบัญชีที่เป็นเครือข่ายเดียวกันถูกครอบเป็นกลุ่ม คลิกแล้วเปิดเคสทั้งเครือข่ายได้

### 4. Reconciliation (กระทบยอดธุรกรรม)

กระทบยอด 3 แหล่ง: ledger ภายใน × ไฟล์ settlement จาก payment gateway / PromptPay × statement ธนาคาร (อัปโหลด CSV หรือดึงตามรอบ)

1. จับคู่ตรงตัวด้วยเลขอ้างอิง
2. จับคู่ด้วยยอด + ช่วงเวลา (เช่น ± 2 วันทำการ) + ชื่อแบบ fuzzy
3. จับคู่แบบหลายต่อหนึ่ง (settlement ก้อนเดียว = หลายธุรกรรม หักค่าธรรมเนียม)
4. รายการที่เหลือให้ AI จัดประเภท: ต่างเวลา (timing), ค่าธรรมเนียม, ยอดไม่ตรง, ซ้ำ, ไม่มีในธนาคาร แล้วร่าง journal entry ปรับปรุงให้คนกดยืนยัน

จุดเชื่อมกับ fraud: รายการที่กระทบยอดไม่ได้ซ้ำๆ ที่บัญชีเดิม (เช่น โอนกลับบ่อย, ยอดหาย) กลายเป็น signal เข้าโมดูล 1

### 5. Payment Follow-ups (ติดตามการชำระเงิน)

Agent ดูแลคิวงานติดตาม 3 ประเภท

| ประเภท | ตัวอย่าง | Agent ทำอะไร |
| --- | --- | --- |
| ยอดค้างจากการกระทบยอด | merchant ค้างค่าธรรมเนียม, settlement ไม่เข้า | ร่างอีเมลเตือนไล่ระดับ, บันทึกวันที่สัญญาว่าจะจ่าย, ยกระดับเมื่อเลยกำหนด |
| เงินที่ต้องคืนผู้เสียหาย | เงินที่ถูกพักไว้จากเคสบัญชีม้า | ติดตามสถานะการคืนเงิน, แจ้งความคืบหน้าผู้เสียหาย |
| ธุรกรรมล้มเหลว / chargeback | โอนไม่สำเร็จ, ลูกค้าโต้แย้งรายการ | เปิดงานติดตาม, ขอเอกสารเพิ่ม, ส่งต่อให้คนตัดสิน |

ทุกข้อความที่จะส่งออกไปต้องผ่านการอนุมัติจากคนก่อน (ตั้งให้ส่งเองได้เฉพาะข้อความเตือนระดับแรก) ในเดโมส่งเข้า inbox จำลอง (เช่น Mailpit) แทนการส่งจริง

### 6. Scenario Studio

Analyst พิมพ์อธิบายรูปแบบที่อยากจับเป็นภาษาคน → LLM แปลงเป็นกฎแบบ JSON DSL (ไม่ใช่ SQL ดิบ เพื่อความปลอดภัย) → ทดสอบย้อนหลัง 30 วัน → แสดงจำนวน alert, precision และตัวอย่างเคสที่จะจับได้ → ผู้จัดการกดเปิดใช้

## Model Tuning Studio

ผู้ดูแลโมเดลปรับจูนได้ 3 ส่วนจากหน้าเว็บเดียว ทุก job รันบน Vultr ทั้งหมด และทุกรุ่นต้องชนะรุ่นปัจจุบันและผ่านการอนุมัติก่อนขึ้น production

| ส่วนที่ปรับ | ปรับอะไรได้ | รันที่ไหนบน Vultr | วัดผลด้วย |
| --- | --- | --- | --- |
| A. โมเดลตรวจจับ (LightGBM) | เทรนใหม่จาก label ของ analyst, เปิดปิด feature, hyperparameter (learning rate, num_leaves, class weight), ค้นอัตโนมัติด้วย Optuna | Training VM แบบ CPU ที่สร้างผ่าน Vultr API ตอนกดเทรน แล้วลบทิ้งเมื่อเสร็จ; ไฟล์โมเดลเก็บใน Object Storage | PR-AUC, precision@100, recall, จำนวน alert ต่อวัน |
| B. Threshold และ scenario | slider เกณฑ์คะแนน และค่าในกฎ (เช่น เงินออก ≥ 90% ภายใน 30 นาที) พร้อมกราฟแลกเปลี่ยน recall กับปริมาณงาน | Worker VM หลัก (backtest บน Postgres ของ Supabase) | alert ที่จะเกิด, false positive rate |
| C. LLM Investigator | เลือกโมเดลจากรายการบน Serverless Inference, เวอร์ชัน system prompt, ตัวอย่าง few-shot จากเคสที่ analyst แก้ไข, เอกสาร typology ใน RAG collection | Vultr Serverless Inference + Vector Store | อัตราที่คำแนะนำตรงกับการตัดสินของ analyst บนชุดเคสทดสอบ |

**วงจรการปรับโมเดล (A)**

1. Analyst ปิดเคสพร้อมผล (fraud จริง / false positive) ผลนี้กลายเป็น label ใน Postgres
2. ผู้ดูแลเปิดหน้า Tuning เลือกช่วงข้อมูล, feature และ hyperparameter แล้วกด Train
3. API สร้าง Training VM ผ่าน Vultr API → job ดึงข้อมูล เทรน และส่ง log สดกลับมาที่หน้าเว็บผ่าน NATS
4. ไฟล์โมเดล + model card เก็บใน Object Storage และ model registry ใน Postgres จากนั้นลบ VM ทิ้ง
5. หน้าเทียบ Champion vs Challenger แสดง metric บนชุด holdout เดียวกัน + เคสที่รุ่นใหม่จับได้เพิ่ม / พลาด
6. เปิด Shadow mode ให้รุ่นใหม่ให้คะแนนคู่กันโดยไม่สร้าง alert จริง
7. Compliance Manager กด Promote (หรือ Rollback กลับรุ่นก่อนได้ในคลิกเดียว) → บันทึกลง audit log แล้ววนกลับไปข้อ 1

จุดขายในวิดีโอคือข้อ 3: เห็น VM ใหม่เกิดขึ้นบน Vultr เทรนเสร็จแล้วหายไป แสดงว่า Vultr เป็น control layer จริง ไม่ใช่แค่ที่ตั้ง server

**ทำไมไม่ fine-tune LLM:** งานนี้ไม่มี Vultr GPU ให้ใช้ และงานตรวจจับจากตารางธุรกรรม โมเดล gradient boosting ทำได้ดีและอธิบายได้มากกว่า ส่วน LLM ปรับผ่าน prompt, few-shot และ RAG ซึ่งเห็นผลทันทีและย้อนกลับได้

## Architecture บน Vultr

ทุกส่วนของระบบรันบน Vultr ประกอบด้วย VM 3 ตัว (App, Worker, Data) ที่จัดการด้วย Coolify, Training VM ที่สร้างและลบผ่าน Vultr API, Supabase on Vultr เป็นฐานข้อมูล + login + realtime, NATS JetStream, Object Storage และ Serverless Inference สำหรับ LLM — Supabase และ Coolify เป็นเครื่องมือที่ผู้จัดแนะนำสำหรับ Challenge 2

```text
Users (browser)
   │ HTTPS
   ▼
Vultr Firewall (80/443 only) ── HTTPS terminated by Coolify proxy
   │
   ▼                    Vultr VPC (private network)
┌──────────────────────────────────────────────────────────────┐
│ App VM: Coolify, SvelteKit web, FastAPI API                  │
│    │ jobs (NATS)            │ "train" → Vultr API            │
│    ▼                        ▼                                │
│ Worker VM: scoring, recon,  Training VM (on demand, CPU,     │
│ agents, follow-ups          LightGBM + Optuna; created and   │
│    │                        deleted via Vultr API)           │
│    ▼                                                         │
│ Data VM: Supabase (Postgres + pgvector, Auth, Realtime)      │
│          + NATS JetStream (transaction stream, job queues)   │
│ Vultr Object Storage: statements, files, model artifacts     │
└──────────────────────────────────────────────────────────────┘
Worker VM ──► Vultr Serverless Inference (LLM agents, Vector Store RAG)
              https://api.vultrinference.com/v1
```

เส้นแนวตั้งแสดงเฉพาะที่เก็บข้อมูลหลักของแต่ละ VM จริงๆ แล้วทุก VM ใน VPC เข้าถึงทั้ง 3 ที่เก็บได้ Supabase และ NATS รันบน Data VM ตัวเดียวกัน ส่วน Training VM มีอยู่เฉพาะตอนเทรน หน้าเว็บรับ alert, เคส และ log การเทรนแบบสดผ่าน Supabase Realtime

| บริการ | ใช้ทำอะไร |
| --- | --- |
| Cloud Compute VM × 3 | App VM (Coolify, SvelteKit, FastAPI), Worker VM (detection, recon, agents, scheduler), Data VM (Supabase + NATS) — ตรงตามที่โจทย์บังคับให้มี VM backend |
| Cloud Compute (on demand) + Vultr API | Training VM สำหรับ Model Tuning สร้างจาก snapshot ตอนกดเทรน แล้วลบเมื่อเสร็จ |
| Firewall + VPC | เปิดสาธารณะเฉพาะ port 80/443 ของ App VM ส่วน VM อื่นคุยกันใน private network |
| Supabase on Vultr | Postgres + pgvector (ธุรกรรม, เคส, label, model registry, audit log), Supabase Auth (login ตามบทบาท), Realtime (อัปเดตหน้าเว็บแบบสด) |
| Coolify on Vultr | deploy ทุก service จาก GitHub, ทำ HTTPS ให้อัตโนมัติ, จัดการ VM ทั้ง 3 ตัวจากที่เดียว |
| NATS JetStream (บน Data VM) | stream ธุรกรรมและคิวงานระหว่าง service (ดูหัวข้อ Transaction Streaming) |
| [Object Storage](https://docs.vultr.com/product-overviews) (S3-compatible) | ไฟล์ statement / settlement ดิบ, ไฟล์โมเดล, model card |
| [Serverless Inference](https://docs.vultr.com/products/compute/serverless-inference/vector-store/rag-chat-collection) | LLM ผ่าน endpoint แบบ OpenAI-compatible (`https://api.vultrinference.com/v1`) สำหรับ agent ทุกตัว; Vector Store เก็บเอกสาร typology สำหรับ RAG |
| Managed Apache Kafka (ไม่ใช้ในงานนี้) | ทางเลือกตอน production สลับแทน NATS ได้ผ่าน `EventBus` |

**เช็คก่อนเริ่ม:** เอกสาร Vultr ระบุว่า endpoint RAG รองรับ tool calling เฉพาะบางโมเดล ก่อนเขียน Investigator agent ให้เรียก List Models ดูว่าโมเดลไหนเรียก tool ได้ หรือแยกเป็น 2 ขั้น (ค้น RAG ก่อน แล้วค่อยส่งเข้า chat completion ที่เรียก tool)

Sources: [Vultr product overviews](https://docs.vultr.com/product-overviews) · [Vultr RAG chat completion docs](https://docs.vultr.com/products/compute/serverless-inference/vector-store/rag-chat-collection) · [Tookitaki](https://www.tookitaki.com)

## Transaction Streaming: ใช้ NATS JetStream

เลือก NATS JetStream ที่ติดตั้งเองบน Vultr VM เพราะค่าใช้จ่ายราว $12/เดือน ส่วน Vultr Managed Kafka มีราคาเริ่มต้นสูงกว่าเครดิต $200 ทั้งก้อน NATS ยังทำหน้าที่แทนคิวงานและ log สดได้ในตัวเดียว จึงตัด Managed Valkey ออกจากส่วนที่ต้องมีได้

| เกณฑ์ | NATS JetStream (บน VM) | Vultr Managed Kafka |
| --- | --- | --- |
| ค่าใช้จ่าย | VM 1 vCPU / 2 GB ราว $12/เดือน หรือรวมบน Worker VM ได้ | เริ่มราว $475/เดือน (3 broker) ตาม[รีวิวภายนอก](https://prjs-astro.pages.dev/blog/2026-03-08_vultr_4) — ควรเช็คราคาจริงใน Vultr Console |
| ความทนทานของข้อมูล | เก็บลง disk, ack, replay ได้ | เหมือนกัน + replicate ข้าม 3 broker |
| ลำดับธุรกรรม | เรียงต่อ subject | เรียงต่อ partition |
| การติดตั้ง | binary เดียว ใช้ RAM น้อย | Vultr ดูแลให้ แต่ต้องตั้ง topic และ ACL เอง |
| ในสายตากรรมการ | ตัดสินใจเรื่องต้นทุนได้สมเหตุสมผล | ใช้ managed service ของ Vultr เพิ่มอีก 1 ตัว |

เขียน producer และ consumer ผ่าน interface `EventBus` ตัวเดียว ตอน pitch จะบอกได้ว่า production สลับไปใช้ Vultr Managed Kafka ได้โดยไม่ต้องแก้ logic

**ออกแบบให้เงินไม่หายและไม่นับซ้ำ**

1. **Outbox pattern:** API บันทึกธุรกรรมกับแถว `outbox` ใน Postgres transaction เดียวกัน แล้ว relay ค่อย publish เข้า NATS ถ้า NATS ล่ม event ไม่หาย
2. **กันซ้ำ (idempotency):** ใช้ transaction id เป็น `Nats-Msg-Id` ให้ JetStream ตัดซ้ำในช่วง dedup window และใส่ unique constraint ที่ `transactions.id` กันอีกชั้น
3. **ลำดับต่อบัญชี:** subject `txn.raw.<shard>` โดย shard = hash(account_id) mod 8 ธุรกรรมของบัญชีเดียวกันจึงเข้า consumer ตามลำดับ
4. **Ack + retry + dead-letter:** durable pull consumer, ส่งซ้ำได้สูงสุด 5 ครั้ง แล้วย้ายไป `txn.dlq` ซึ่งแสดงในหน้า Infra ให้คนกด replay
5. **Replay:** เก็บ stream 7 วัน ใช้ทำ backtest ใน Scenario Studio และ reset เดโมให้เหมือนเดิมทุกรอบ
6. **จำนวนเงิน:** เก็บเป็นสตางค์แบบจำนวนเต็ม (BIGINT) ไม่ใช้ float — คอลัมน์ลงท้ายด้วย `_satang`
7. **ความปลอดภัย:** NATS เปิดเฉพาะใน VPC, ใช้ TLS + user credentials, ไม่มี port สาธารณะ

Subject อื่นที่ใช้: `txn.scored`, `alerts.new`, `recon.files`, `jobs.<workflow>`, `train.logs.<job_id>`

**งบประมาณต่อเดือน (ประมาณการ ควรเช็คใน Vultr Console)**

| รายการ | สเปก | USD/เดือน |
| --- | --- | --- |
| App VM (Coolify + web + API) | 2 vCPU / 4 GB | ~24 |
| Worker VM | 2 vCPU / 4 GB | ~24 |
| Data VM (Supabase + NATS) | 4 vCPU / 8 GB | ~48 |
| Object Storage | tier เล็กสุด | ~5 |
| Training VM | คิดรายชั่วโมง เปิดไม่กี่นาทีต่อครั้ง | < 2 |
| Serverless Inference | ตามแพ็กเกจที่เลือก | เช็คใน Console |
| **รวม (ไม่นับ Inference)** |  | **~103** |

เครดิต $200 ใช้ได้ตลอดช่วงงาน (3–8 พ.ย. 2026) และ Vultr คิดเงินรายชั่วโมง ชุดด้านบนเปิด 5 วันจะใช้จริงราว $17 ไม่ต้องใช้ Load Balancer เพราะ Coolify ทำ HTTPS ให้เอง ควรพัฒนาบนเครื่องตัวเองด้วย Docker Compose ก่อน แล้วค่อยขึ้น Vultr ราคาอ้างอิงจาก[หน้ารวมราคาภายนอก](https://prjs-astro.pages.dev/blog/2026-03-08_vultr_4)

## Data model

ตารางหลัก 14 ตาราง (+ `outbox` และ `train_runs`) อยู่ใน Postgres ของ Supabase เปิด pgvector ไว้ค้นเคสที่คล้ายกัน และเปิด Row Level Security ตามบทบาททุกตาราง

| กลุ่ม | ตาราง | คอลัมน์สำคัญ |
| --- | --- | --- |
| ลูกค้าและบัญชี | `customers` | id, name_th, name_en, kyc_level, risk_score, created_at |
|  | `accounts` | id, customer_id, type (wallet / bank / merchant), bank_code, opened_at, status (active / frozen) |
| ธุรกรรม | `transactions` | id, from_account, to_account, amount_satang, channel (PromptPay / transfer / QR), ref_no, ts, device_id |
|  | `settlements` | id, source (gateway / bank), ref_no, amount_satang, fee_satang, value_date, raw_file_key |
| ตรวจจับ | `scenarios` | id, name, dsl_json, version, status (draft / active), created_by |
|  | `alerts` | id, transaction_id, account_id, scenario_id, model_version, score, top_features_json, priority |
| เคส | `cases` | id, type (mule / recon_break / follow_up), status, assignee, disposition, ai_summary, str_draft |
|  | `case_links` | case_id, alert_id หรือ account_id หรือ transaction_id |
| กระทบยอด | `recon_runs` | id, period, matched_count, break_count, status |
|  | `recon_matches` | run_id, transaction_id, settlement_id, match_rule, confidence, break_type |
| ติดตาม | `follow_ups` | id, case_id, counterparty, amount_due_satang, due_date, stage, promise_date, next_action_at |
|  | `messages` | id, follow_up_id, channel, draft, approved_by, sent_at |
| โมเดล | `model_versions` | id, kind (lgbm / prompt / scenario), params_json, metrics_json, artifact_key, stage (challenger / shadow / champion) |
| Audit | `audit_log` | id, actor (user / agent), action, object_ref, before_json, after_json, ts |

ส่วนที่เก็บนอก Postgres: ไฟล์ statement / settlement ดิบ, ไฟล์โมเดล และ model card อยู่ใน Vultr Object Storage; stream ธุรกรรม, คิวงาน และ log สดอยู่ใน NATS JetStream

## Agent workflows

ทุก workflow เป็น job ในคิว (NATS JetStream) ที่ทำงานต่อเนื่องเอง และหยุดรอคนทุกครั้งที่มี action ที่กระทบเงินหรือลูกค้า (✳ = จุดที่คนต้องอนุมัติ)

**W1 · Detect → Investigate (ทุกธุรกรรม)**

1. Simulator ส่งธุรกรรมเข้า stream (เช่น 5–20 รายการต่อวินาทีในเดโม)
2. Scoring worker รันกฎ + LightGBM + graph features → เกินเกณฑ์สร้าง alert
3. Alert ที่เชื่อมบัญชีเดียวกันถูกรวมเป็นเคสเดียว
4. Investigator agent เรียก tool: `get_account_history`, `expand_graph(hops=2)`, `screen_name`, `search_typology` (RAG), `similar_cases` (pgvector)
5. Agent เขียนสรุปเคส + จัดลำดับ + แนะนำ action พร้อมหลักฐานทุกข้อ
6. ✳ Analyst ตัดสิน: ปิด / ยกระดับ / ระงับบัญชี / อนุมัติร่าง STR → ผลกลายเป็น label ให้ Tuning Studio
7. ถ้ามีเงินผู้เสียหายที่พักไว้ได้ → สร้างงานใน W3 อัตโนมัติ

**W2 · Daily Reconciliation (ตามรอบทุกวัน หรืออัปโหลดไฟล์)**

1. ไฟล์ settlement / statement เข้า Object Storage → parser แปลงเป็น `settlements`
2. Matching engine รัน 3 รอบ (เลขอ้างอิง → ยอด + เวลา + fuzzy → หลายต่อหนึ่ง)
3. Recon agent จัดประเภทรายการที่เหลือและร่าง journal entry
4. ✳ Finance Ops ยืนยัน journal entry; รายการค้างจ่ายส่งต่อ W3, รายการน่าสงสัยส่งต่อ W1

**W3 · Payment Follow-up (รันทุกชั่วโมง)**

1. เลือกงานที่ `next_action_at` ถึงเวลา
2. Follow-up agent ดูประวัติการติดตาม เลือกระดับข้อความ และร่างข้อความภาษาไทย / อังกฤษ
3. ✳ เจ้าหน้าที่อนุมัติ (ข้อความเตือนระดับแรกส่งเองได้ถ้าเปิดตั้งค่า)
4. อ่านคำตอบ (เช่น "จะโอนวันศุกร์") → บันทึก `promise_date` → เลยกำหนดจะยกระดับให้คนดู
5. เงินเข้าแล้วตรวจพบใน W2 → ปิดงานอัตโนมัติ

**W4 · Model Tuning** ตามวงจรในหัวข้อ Model Tuning Studio

**Guardrail ของ agent:** tool ทุกตัวอ่านอย่างเดียว ยกเว้น `propose_action` ที่เขียนได้แค่คำแนะนำรออนุมัติ, จำกัดจำนวน tool call ต่อเคส, และบันทึก prompt + ผลทุกครั้งลง audit_log

## หน้าจอ web app

ทำเป็น SvelteKit (Svelte 5) + Tailwind CSS v4 + shadcn-svelte login ด้วย Supabase Auth แยกสิทธิ์ตามบทบาท และสลับภาษาไทย / อังกฤษ (ในวิดีโอใช้อังกฤษเพราะกรรมการเป็นนานาชาติ) มีบัญชีเดโมแยกตามบทบาทให้กรรมการลองใช้

| หน้า | สิ่งที่เห็น | ผู้ใช้ |
| --- | --- | --- |
| Command Center | ธุรกรรมต่อนาที (live), alert ใหม่, เคสค้าง, ยอดเงินที่พักได้, recon วันนี้ | ทุกคน |
| Alert Queue | รายการ alert เรียงตาม priority ของ AI พร้อมเหตุผล 1 บรรทัด | Analyst |
| Case Detail | สรุป AI, timeline ธุรกรรม, กราฟย่อ, หลักฐาน, ปุ่มตัดสิน, ตัวแก้ไขร่าง STR | Analyst |
| Graph Explorer | กราฟเต็มจอ, ขยาย hop, time slider, Trace from victim, กลุ่มเครือข่าย | Analyst |
| Reconciliation | อัปโหลดไฟล์, อัตราจับคู่, รายการ break แยกประเภท, ยืนยัน journal entry | Finance Ops |
| Follow-ups | Kanban ตาม stage, ร่างข้อความรออนุมัติ, วันที่สัญญาว่าจะจ่าย | Collections |
| Scenario Studio | ช่องพิมพ์ภาษาคน, DSL ที่ได้, ผล backtest | Compliance Manager |
| Model Tuning | ฟอร์มเทรน, log สด, Champion vs Challenger, slider threshold, prompt versions, Promote / Rollback | Model Owner |
| Audit Log | ทุก action ของคนและ agent ค้นหาได้ | Compliance Manager |
| Infra (Vultr) | สถานะ VM, คิวงาน, Training VM ที่กำลังทำงาน, จำนวน token ที่ใช้ ดึงจาก Vultr API | Admin / กรรมการ |

### UI style guide

อ้างอิงอารมณ์จาก [Dashboard UI Design – AI Assistant (Nixtio, Dribbble)](https://dribbble.com/shots/26081670-Dashboard-UI-Design-AI-Assistant) — ใช้เป็นแนวทาง ไม่ลอกงาน

- **พื้นหลัง:** gradient นุ่มฟ้าอมม่วง จาก `#ECF0F8` ไป `#9CA7DE` (ขอบล่าง/มุม) ทั้งหน้า
- **โครงหน้า:** แผงหลักสีขาวโปร่ง (glassmorphism: `bg-white/70 backdrop-blur`) มุมมนใหญ่ (`rounded-3xl`) ลอยบนพื้นหลัง; แถบไอคอนแนวตั้งบางๆ ด้านซ้าย (ปุ่มกลม); top bar มีตัวเลือก workspace ทางซ้าย ชื่อหน้าตรงกลาง ปุ่ม pill สีเข้มทางขวา
- **การ์ด:** สีขาว `rounded-2xl` เงานุ่ม (`shadow-[0_8px_30px_rgba(77,80,110,0.08)]`) ไม่มีเส้นขอบหนา, ไอคอนสีอยู่มุมบนซ้าย, หัวข้อตัวหนาสีเข้ม, คำอธิบายสั้น, label เล็กสีเทาด้านล่าง
- **ตัวอักษร:** หัวข้อใหญ่ hero แบบ "Hi Analyst, **3 rings need you today**" (ส่วนสำคัญหนา ส่วนรองสีจาง); ฟอนต์ sans เรียบ (Inter / IBM Plex Sans Thai สำหรับภาษาไทย)
- **AI bar:** กล่อง prompt ด้านล่างของ Command Center / Case Detail แบบในภาพ: ช่องพิมพ์ + ปุ่มส่งกลมสีเข้ม + แถว chip pill สีเข้ม (`#05060B`) เช่น "Investigate", "Trace from victim", "Draft STR", "Explain score"
- **สี (tokens):**

| Token | Hex | ใช้กับ |
| --- | --- | --- |
| `--bg-from` | `#ECF0F8` | พื้นหลังสว่าง |
| `--bg-to` | `#9CA7DE` | ปลาย gradient |
| `--ink` | `#05060B` | ตัวอักษรหลัก, ปุ่ม pill, chip |
| `--ink-muted` | `#4D506E` | ตัวอักษรรอง |
| `--accent` | `#6C72AC` | ลิงก์, focus ring, กราฟปกติ |
| `--alert` | `#EC630D` | ความเสี่ยงสูง, badge alert, node บัญชีม้า |

- **ข้อมูลความเสี่ยง:** คะแนน 0–100 ใช้ ramp จาก `--accent` (ต่ำ) ไป `--alert` (สูง); ห้ามใช้สีแดง/เขียวสดที่แข่งกับ accent
- **Motion:** transition สั้น (150–200 ms), alert ใหม่เลื่อนเข้าพร้อม highlight ส้มจางแล้วหาย
- **Dark mode:** ไม่ทำในรอบ hackathon

## Demo script, แผนงาน และความเสี่ยง

**วิดีโอ 3 นาที (เล่าเป็นเคสเดียวตั้งแต่ต้นจนจบ)**

1. **0:00–0:20** ปัญหา: ผู้เสียหายถูกหลอกโอน เงินหายผ่านบัญชีม้าหลายทอดภายในไม่กี่นาที
2. **0:20–0:50** Command Center: ธุรกรรมไหลสด → alert เด้งขึ้นพร้อมเหตุผล "รับจาก 14 บัญชีใหม่ โอนออก 96% ภายใน 8 นาที"
3. **0:50–1:30** Case + Graph Explorer: กด Trace from victim เห็นเครือข่าย 3 ชั้น และเงินที่ยังค้างอยู่ → AI สรุปและร่าง STR → analyst กดระงับ
4. **1:30–1:55** Follow-ups: งานคืนเงินผู้เสียหายถูกสร้างอัตโนมัติ + ร่างข้อความรออนุมัติ
5. **1:55–2:15** Reconciliation: อัปโหลด settlement จับคู่อัตโนมัติ เหลือ break ที่ AI อธิบายและร่าง journal entry
6. **2:15–2:45** Model Tuning: กด Train → เห็น Training VM เกิดบน Vultr → Challenger ชนะ Champion → Promote
7. **2:45–3:00** Architecture บน Vultr + หน้า Audit Log ปิดท้าย

**แผนงาน: ส่งงานภายใน 8 พ.ย. 2026 — ทำข้อ 1–4 ให้ครบก่อน ข้อ 5–7 ทำเท่าที่จะโชว์ในวิดีโอ**

1. **4 พ.ย.** M1: repo, Docker Compose, schema, data generator ที่ฝังเครือข่ายบัญชีม้า
2. **5 พ.ย.** M2–M3: NATS pipeline, กฎ 5 ตัว + LightGBM baseline, Alert Queue, Case Detail, Investigator agent
3. **6 พ.ย.** M4–M5: Graph Explorer, Model Tuning + Training VM, deploy ขึ้น Vultr ด้วย Coolify
4. **7 พ.ย.** M6–M7: Reconciliation และ Follow-ups แบบพอโชว์, README, อัดวิดีโอ, สไลด์, รูปปก
5. **8 พ.ย.** เผื่อเวลาแก้บั๊ก แล้วส่งบน lablab.ai (เช็คเวลาปิดรับที่แน่นอนใน Discord)

Scenario Studio และการปรับ prompt (ส่วน C) ทำเฉพาะถ้าเหลือเวลา

**ความเสี่ยง**

| ความเสี่ยง | ทางแก้ |
| --- | --- |
| ขอบเขตใหญ่เกินเวลา hackathon | ทำตามลำดับด้านบน โมดูล 5–7 ทำแค่ส่วนที่อยู่ในวิดีโอก็ได้ |
| กรรมการมองว่าเป็น compliance ธนาคาร ไม่ใช่ Finance | เล่าเป็น "Finance Ops ของ e-wallet" และชี้ให้เห็นว่าครบทั้ง reconcile, flag anomalies และ payment follow-ups ตามโจทย์ |
| เทรนบน VM ใหม่ช้าตอนอัดวิดีโอ | เตรียม snapshot ที่ติดตั้ง dependency ไว้แล้ว และใช้ชุดข้อมูลเล็ก (หลักแสนแถว) |
| LLM ตอบผิดหรือแต่งข้อมูล | ให้ agent อ้างอิง id ธุรกรรมจริงทุกข้อ และตรวจว่า id มีอยู่จริงก่อนแสดง |
| ค่าใช้จ่าย Vultr บานปลาย | ตั้ง TTL ให้ Training VM ลบตัวเองหลัง 30 นาที และใช้แพลนเล็กสุดที่พอ |

## Handoff สำหรับ Claude Code

ส่วนนี้คือ spec ให้ Claude Code ตั้งโปรเจกต่อ

```text
Read docs/DESIGN.md fully, especially "Handoff สำหรับ Claude Code".
Build Zentry as a public, MIT-licensed monorepo exactly as specified there.
First create CLAUDE.md summarising stack, layout, commands and rules from the doc.
Work one milestone at a time (M1 → M7). After each milestone, run its acceptance
checks, show me the results, and stop for my review before continuing.
Rules: synthetic data only; never commit secrets (.env.example only); never create,
resize or delete paid Vultr resources without asking me first; amounts are integer
satang (BIGINT); every agent claim must cite real transaction ids.
Start with M1.
```

### Stack

| ส่วน | เทคโนโลยี |
| --- | --- |
| Web | SvelteKit (Svelte 5, TypeScript, adapter-node), Tailwind CSS v4, shadcn-svelte, Cytoscape.js, supabase-js + @supabase/ssr (Auth + Realtime) |
| API | FastAPI, Python 3.12, psycopg 3, pydantic v2 |
| Worker | Python 3.12, nats-py, LightGBM, scikit-learn, NetworkX, SHAP, openai SDK (base_url ชี้ไป Vultr Serverless Inference) |
| Trainer | Python 3.12 container: LightGBM + Optuna, อัปโหลดผลด้วย boto3 (S3-compatible) |
| Data | Supabase (Postgres + pgvector, Auth, Realtime), NATS JetStream |
| Local dev | Supabase CLI (`supabase start`) + Docker Compose (`nats -js` + ทุก service) |
| Prod | Coolify บน App VM จัดการ App / Worker / Data VM ผ่าน SSH; Supabase ติดตั้งเป็น service ใน Coolify |

### Repo layout

```text
zentry/
├─ apps/web/               # SvelteKit UI (10 หน้าตามหัวข้อ หน้าจอ web app)
├─ services/api/           # FastAPI: cases, decisions, train, recon upload, Vultr API calls
├─ services/worker/        # NATS consumers: scoring, investigator, recon, follow-up, outbox relay
├─ services/trainer/       # training job image (runs on Training VM or locally)
├─ libs/zt_core/           # shared Python: EventBus, scenario DSL, features, money utils
├─ supabase/migrations/    # SQL schema + RLS + seed roles
├─ data/generator/         # synthetic customers, txns, mule rings, settlements
├─ infra/
│  ├─ docker-compose.yml
│  ├─ coolify/             # deploy notes + env per service
│  └─ vultr/               # cloud-init for Training VM, firewall + VPC setup script
├─ docs/DESIGN.md          # เอกสารนี้
├─ docs/architecture.png
├─ scripts/demo_reset.sh   # ล้างข้อมูล + replay stream ให้เดโมเหมือนเดิม
├─ CLAUDE.md, README.md, LICENSE (MIT), .env.example, Makefile
```

### Environment variables

| ตัวแปร | ใช้ที่ | หมายเหตุ |
| --- | --- | --- |
| `PUBLIC_SUPABASE_URL`, `PUBLIC_SUPABASE_ANON_KEY` | web | เปิดเผยได้ คุมสิทธิ์ด้วย RLS (SvelteKit ใช้ prefix `PUBLIC_`) |
| `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL` | api, worker | ห้ามส่งให้ browser หรือ Training VM |
| `NATS_URL`, `NATS_CREDS` | api, worker | เข้าถึงได้เฉพาะใน VPC |
| `VULTR_API_KEY` | api | ใช้สร้าง / ลบ Training VM เท่านั้น; ไม่ตั้ง = เทรนเป็น container บนเครื่อง |
| `VULTR_TRAIN_SNAPSHOT_ID`, `VULTR_REGION`, `VULTR_TRAIN_PLAN`, `VULTR_VPC_ID` | api | สเปก Training VM |
| `VULTR_INFERENCE_API_KEY`, `VULTR_INFERENCE_BASE_URL=https://api.vultrinference.com/v1`, `LLM_MODEL` | worker | เลือกโมเดลที่รองรับ tool calling |
| `VULTR_VECTOR_COLLECTION_ID` | worker | RAG typology |
| `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` | api, worker | Training VM ได้แค่ pre-signed URL ไม่ใช่ key |

### Milestones และเกณฑ์ผ่าน

1. **M1 Foundation** — `make up` เปิดทุก service บนเครื่อง; migration สร้างทุกตารางตาม Data model + RLS; `make seed` สร้างลูกค้า 10,000 คน ธุรกรรมราว 200,000 รายการใน 30 วัน ฝังเครือข่ายบัญชีม้า 5 วง (3 ชั้น, วงละ 10–20 บัญชี) พร้อม label และไฟล์ settlement ที่มี break ฝังไว้ → ผ่านเมื่อ query นับจำนวนได้ตรง และ login ด้วยบัญชีเดโม 4 บทบาทได้
2. **M2 Detection** — simulator replay ธุรกรรมเข้า NATS (ปรับความเร็วได้); outbox relay, dedup ด้วย `Nats-Msg-Id`, shard ตาม account; worker ให้คะแนนด้วยกฎ 5 ตัว + LightGBM baseline + graph features แล้วสร้าง alert ที่ขึ้น Alert Queue แบบ realtime → ผ่านเมื่อบัญชีม้าที่ฝังไว้ถูกตั้งธง ≥ 80% และส่งข้อความซ้ำ 2 ครั้งได้แถวเดียว
3. **M3 Investigation** — Case Detail + Investigator agent พร้อม tool ตาม W1, ร่าง STR, analyst ตัดสินแล้วเขียน `audit_log` + label → ผ่านเมื่อ validator ยืนยันว่าทุก id ที่ agent อ้างมีอยู่จริง และ agent ไม่มี tool ที่เขียนข้อมูลนอกจาก `propose_action`
4. **M4 Graph Explorer** — `/graph?account=` ขยาย hop, time slider, Trace from victim, กลุ่มเครือข่าย → ผ่านเมื่อเห็นวงบัญชีม้าครบทั้งวงภายใน 2 คลิกจากเคส
5. **M5 Model Tuning** — `POST /train` สร้าง Training VM จาก snapshot ผ่าน Vultr API (tag `zentry-train`, cloud-init รัน trainer) → trainer ดึงข้อมูลด้วย token อายุสั้น เทรน อัปโหลด artifact ผ่าน pre-signed URL แล้วรายงาน metric → API ลบ VM; watchdog ลบ VM ที่เกิน 30 นาที; หน้า Champion vs Challenger, threshold slider, Shadow, Promote / Rollback → ผ่านเมื่อเห็น VM เกิดและหายใน Vultr Console และโหมด local ทำงานเมื่อไม่มี `VULTR_API_KEY`
6. **M6 Recon + Follow-ups** — อัปโหลด settlement, matching 3 รอบ, AI จัดประเภท break + ร่าง journal entry; Kanban follow-up + ร่างข้อความรออนุมัติ → ผ่านเมื่อ break ที่ฝังไว้ถูกจับได้ครบ
7. **M7 Deploy + ส่งงาน** — ติดตั้ง Coolify บน App VM, เพิ่ม Worker / Data VM, Supabase บน Data VM, firewall เปิดแค่ 80/443, โดเมน + HTTPS; README (บริการ Vultr ที่ใช้, รูป architecture, วิธี setup, บัญชีเดโม), `scripts/demo_reset.sh` → ผ่านเมื่อเปิด URL สาธารณะจากเครื่องอื่นแล้วเดิน demo script ได้ครบ

**สิ่งที่คนต้องทำเอง (Claude Code ทำแทนไม่ได้)**

- [ ] ใส่โค้ดเครดิต $200 ใน Vultr Billing (อีเมลต้องไม่เคยมีบัญชี Vultr)
- [ ] สร้าง API key, Inference key, Object Storage bucket แล้วใส่ใน `.env` เอง
- [ ] เลือก region เดียวกันทุก service (เช่น Singapore)
- [ ] เช็คเวลาปิดรับงานใน Discord และส่งงานบน lablab.ai (วิดีโอ, สไลด์, รูปปก, คำอธิบาย)

Source: [Vultr Hackathon rules — lablab.ai](https://lablab.ai/ai-hackathons/vultr-hackathon)
