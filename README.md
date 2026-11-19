# AI Orchestrator POC

## Tổng quan

AI Orchestrator nhận câu hỏi và thử nghiệm cách định tuyến đến sáu nhóm intent cho một trợ lý nghiệp vụ phần mềm. Mục tiêu của POC là kiểm chứng phân loại và fallback trước khi kết nối các công cụ truy xuất dữ liệu.

## Kiến trúc

FastAPI cung cấp các endpoint thử nghiệm. Request đi qua Pydantic để kiểm tra đầu vào rồi đến service tương ứng.

- **Gemini Decision 1** phân loại theo bộ tiêu chí V1 hoặc V2 và trả confidence cùng phân bố xác suất.
- **Gemini 3.5 Flash-Lite** sinh văn bản cho endpoint chat và phân loại lại khi Decision 1 có confidence thấp ở endpoint route. Fallback trả một nhãn có cấu trúc. Nếu kết quả chưa xác nhận, API trả `final_intent: null`.
- **Query Planner** dự kiến dùng Flash-Lite để lập kế hoạch truy vấn sau khi có intent. Phần này chưa được triển khai.

## Công nghệ

Python 3.12, FastAPI, Uvicorn, Pydantic Settings, Google Gen AI SDK, HTTPX và Pytest. PostgreSQL tương lai phục vụ KPI, pgvector phục vụ RAG và Neo4j phục vụ truy vấn quan hệ.

## Chức năng đã triển khai

- Hai endpoint trạng thái và tài liệu OpenAPI/Swagger.
- Chat văn bản với Flash-Lite.
- Intent Classification bằng Decision 1, hỗ trợ V1/V2.
- Routing V2 theo confidence và fallback Flash-Lite.
- Công cụ đánh giá intent, so sánh kết quả V1/V2 và đánh giá fallback từ báo cáo đã lưu.

## Cấu trúc dự án

```text
app/
  api/        Các endpoint FastAPI
  core/       Cấu hình môi trường
  schemas/    Schema request và response
  services/   Gemini, tiêu chí intent và routing
  tools/      Chỗ dành cho tích hợp công cụ
data/         Dataset giả lập, câu hỏi ngoài nghiệp vụ và tập độc lập
scripts/      Đánh giá intent, fallback và so sánh kết quả
tests/        Kiểm thử API và đánh giá bằng mock
```

## Thiết lập môi trường

Cài Git và Miniconda hoặc Conda trước. Trong PowerShell đã cấu hình Conda, chạy:

```powershell
git clone https://github.com/viethung21IT/ai-orchestrator-poc.git
Set-Location ai-orchestrator-poc
conda create -n orchestrator_env --override-channels -c conda-forge python=3.12 pip
conda activate orchestrator_env
$env:PYTHONNOUSERSITE = '1'
python -m pip install -r requirements.txt
python -m pip check
```

Nếu `orchestrator_env` đã có, bỏ qua lệnh tạo. Trong VS Code, chọn môi trường này qua **Python: Select Interpreter**. Đặt lại `PYTHONNOUSERSITE=1` mỗi khi mở terminal mới. Trong CMD, dùng `set "PYTHONNOUSERSITE=1"`. Biến này giúp Python bỏ qua thư viện của tài khoản Windows để tránh xung đột Pydantic.

```powershell
python -c "import site, pydantic; print(site.ENABLE_USER_SITE); print(pydantic.__file__)"
```

Kết quả mong đợi là `False` và đường dẫn Pydantic thuộc `orchestrator_env`.

## Cấu hình

Nếu chưa có `.env`, tạo từ `.env.example` bằng `Copy-Item .env.example .env`. Điền `GEMINI_API_KEY` trong file local khi cần chạy các endpoint Gemini. Dùng khóa từ project Free Tier của bạn cho POC.

- `GEMINI_MODEL` mặc định là `gemini-3.5-flash-lite`.
- `GEMINI_DECISION_MODEL` mặc định là `gemini-decision-1`.
- `INTENT_CRITERIA_VERSION` chọn `v1` hoặc `v2` cho endpoint classify. Route luôn dùng V2.
- `INTENT_CONFIDENCE_THRESHOLD` mặc định là `0.7`.
- `INTENT_FALLBACK_ENABLED` mặc định là `true`.

Giữ `.env`, credential và dữ liệu nội bộ trên máy local. Khởi động lại API khi đổi cấu hình.

## Chạy FastAPI

Từ thư mục gốc dự án và môi trường đã kích hoạt:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Mở [Swagger UI](http://127.0.0.1:8000/docs). Các endpoint trạng thái hoạt động ngay cả khi chưa thiết lập khóa Gemini.

## API Endpoints

- `GET /` trả thông báo ứng dụng đang chạy.
- `GET /health` trả trạng thái tiến trình FastAPI.
- `POST /api/v1/chat` trả câu trả lời văn bản và tên model.
- `POST /api/v1/classify` trả nhãn, confidence và xác suất cho sáu nhóm.
- `POST /api/v1/route` trả intent ban đầu, intent cuối, trạng thái và thời gian xử lý. Confidence thấp hơn ngưỡng kích hoạt fallback nếu cấu hình bật. Confidence và probabilities trong response thuộc Decision 1.

Ba endpoint POST cùng nhận JSON dạng `{"question":"Quy trình nghiệm thu dự án gồm những bước nào?"}`. Gọi các endpoint này qua Swagger sẽ dùng Gemini thật.

## Unit Testing

```powershell
python -m pytest
python -m pip check
```

Test Gemini dùng HTTP giả lập. Bộ test kiểm tra tập câu hỏi độc lập trong repo. Các test tính chỉ số và đối chiếu phiên bản dùng fixture.

## Dataset dùng chung

`data/synthetic_enterprise_v2/` là Synthetic Enterprise Dataset V2.0, bộ dữ liệu **giả lập** cho POC về hợp đồng và dự án phần mềm. Tên, tài liệu và số liệu đều được tạo cho kiểm thử.

- `structured/` chứa 7 bảng CSV với 20 khách hàng, 40 hợp đồng, 60 dự án, 6 phòng ban, 300 bản ghi tài chính, metadata của 70 tài liệu và 75 liên kết tài liệu–dự án.
- `documents/` chứa 70 tài liệu Markdown, gồm 3 chính sách chung và 67 tài liệu gắn dự án hoặc hợp đồng.
- `evaluation/` chứa 50 câu golden có đáp án và bằng chứng. JSON dùng cho script, CSV phục vụ xem thủ công và `reference_checks.json` lưu kiểm tra tham chiếu.
- `DATA_DICTIONARY.md` ghi các khóa liên kết, công thức KPI và mô hình quan hệ. `validate_dataset.py` kiểm tra dữ liệu offline bằng Python và SQLite trong bộ nhớ.
- `data/intent_other_questions.json` bổ sung 6 câu ngoài nghiệp vụ. `data/intent_independent_questions.json` chứa 30 câu độc lập với 5 câu cho mỗi intent và trường trạng thái bằng chứng riêng.

Kiểm tra dataset từ thư mục gốc:

```powershell
python data/synthetic_enterprise_v2/validate_dataset.py
```

Khi triển khai công cụ, dùng CSV và khóa liên kết cho KPI, đọc Markdown theo đường dẫn trong bảng metadata cho RAG, và dùng các thực thể cùng quan hệ đã mô tả trong Data Dictionary cho Neo4j. Chỉ dùng golden và đáp án tham chiếu để kiểm thử. Giữ dữ liệu thật, tài liệu công ty, khóa và thông tin kết nối ngoài repository.

## Đánh giá Intent Classification

Script mặc định đọc golden trong `data/synthetic_enterprise_v2/evaluation/golden_questions.json`. Dùng `--dataset "<duong-dan-golden_questions.json>"` khi muốn chỉ định file khác, hoặc `--independent` để đọc tập 30 câu độc lập.

```powershell
python -m scripts.evaluate_intent --criteria v2 --dry-run
python -m scripts.evaluate_intent --criteria v2 --independent --dry-run
python -m scripts.evaluate_intent --criteria v2 --limit 5
python -m scripts.compare_intent "<bao-cao-v1>" "<bao-cao-v2>"
python -m scripts.evaluate_fallback "<bao-cao-v2>" --threshold 0.7
python -m scripts.evaluate_fallback "<bao-cao-v2>" --threshold 0.7 --run-api
```

`--dry-run`, `compare_intent` và `evaluate_fallback` khi chưa có `--run-api` chạy offline. Lệnh đánh giá intent có `--limit 5` gọi Decision 1 thật. Lệnh fallback có `--run-api` đọc kết quả Decision 1 đã lưu và chỉ gọi Flash-Lite cho câu dưới ngưỡng. So sánh V1/V2 cần hai lượt có cùng tập câu hỏi. Báo cáo sinh ra trong `evaluation_results/` và lưu cục bộ.

## Chức năng dự kiến và lộ trình

1. Xây dựng **Query Planner** để chuyển intent đã xác nhận thành yêu cầu có cấu trúc.
2. Tích hợp **KPI Tool** cho số liệu, **RAG** cho nội dung tài liệu và **Neo4j** cho truy vấn quan hệ.
3. Điều phối công cụ, tổng hợp câu trả lời có bằng chứng và đánh giá luồng hoàn chỉnh.

## Làm việc nhóm

Giữ `main` cho code ổn định. Hai người có thể làm trên `feature/query-planner` và `feature/kpi-tool`. Ví dụ cho người phụ trách Planner:

```powershell
git switch main
git pull --ff-only
git switch -c feature/query-planner
```

Chạy test, xem `git diff --staged`, kiểm tra file nhạy cảm rồi commit và push nhánh tính năng. Mở Pull Request vào `main` để người còn lại review trước khi merge. Với dữ liệu và báo cáo cục bộ, thống nhất quyền chia sẻ trước khi đưa vào bất kỳ nhánh nào.
