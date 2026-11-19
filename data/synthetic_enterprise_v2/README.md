# Synthetic Enterprise Dataset V2.0

Bộ dữ liệu doanh nghiệp giả lập dành cho POC AI Orchestrator (KPI + RAG + Neo4j). Miền nghiệp vụ: quản lý hợp đồng và dự án tại doanh nghiệp cung cấp dịch vụ phần mềm. Tất cả tên, số liệu, tài liệu và tình huống đều được tạo mới, không phải dữ liệu công ty thật. Không tải/sao chép bản ghi từ dataset công khai. Thiết kế tham khảo ở mức ý tưởng: PMO Analytics (tài chính theo dự án/tháng), Dubai Project Management (thực thể liên kết), Project Atlas (liên kết tài liệu với thực thể). Không khẳng định đã kiểm tra từng dataset nguồn.

## Cấu trúc

- `structured/`: 20 customers, 40 contracts, 60 projects, 6 departments, 300 dòng tài chính, 70 dòng metadata tài liệu, 75 liên kết tài liệu–dự án.
- `documents/`: 70 tài liệu tiếng Việt (Markdown), gồm 3 chính sách chung và 67 tài liệu gắn dự án/hợp đồng.
- `evaluation/`: 50 câu hỏi chuẩn có đáp án và nguồn; JSON dùng cho kiểm thử tự động, CSV để xem thủ công (không phải 2 bộ dữ liệu khác nhau).
- `DATA_DICTIONARY.md`: cấu trúc và quy tắc nghiệp vụ.
- `validate_dataset.py`: chạy bằng Python standard library, kiểm tra dữ liệu offline.

## Cách sử dụng theo kế hoạch

1. Đọc DATA_DICTIONARY, xem CSV và tài liệu, xác nhận bài toán với mentor nếu cần.
2. Chạy `python validate_dataset.py` từ thư mục dataset. Không cần cài thư viện và không kết nối database.
3. Tuần 1: dùng CSV/JSON làm nguồn KPI mock. Tính bằng Python hoặc SQL đã kiểm soát, không giao LLM tính toán. Dùng ID để nối bảng.
4. Tuần 2: đọc 70 file Markdown, chia đoạn, tạo embedding và lưu vào PostgreSQL + pgvector sau khi được phép; giữ document_id, project_id (có thể nhiều), section và tên file. Tài liệu chính sách chung không giới hạn theo project.
5. Tuần 3: tạo nodes/relationships Neo4j từ CSV theo DATA_DICTIONARY. GraphRAG có thể tìm dự án/hợp đồng, tìm document_id liên kết và truy xuất đoạn văn bằng RAG. Với câu hỏi nghiệm thu, truy xuất thêm chính sách chung DOC001 nếu cần.
6. Dùng câu hỏi chuẩn để đánh giá. Đáp án và evidence dùng cho bộ kiểm thử, **không index golden_questions vào RAG**. Một câu hỏi KPI/graph có thể cần thêm bảng tra cứu hoặc định nghĩa KPI.

## Giả định và giới hạn

Snapshot nghiệp vụ 31/10/2026, tài chính tháng 06–10/2026. Tất cả số tiền VND nguyên, không VAT. Giá trị hợp đồng khác doanh thu/tiền thu. Không có dữ liệu hóa đơn, thanh toán, công nợ, nhân viên hoặc phân quyền thật. Không có dữ liệu tài chính ngoài phạm vi kỳ mô phỏng. Không tự suy diễn bằng 0 khi thiếu kỳ. Trạng thái dự án là snapshot, không phải lịch sử. Không tự chạy SQL, cài pgvector, gửi dữ liệu qua API hay nhập vào server công ty. Bộ dữ liệu mở rộng này phục vụ demo chức năng, không chứng minh hiệu năng hoặc độ chính xác production. CSV UTF-8 BOM để Excel đọc tiếng Việt; Python dùng encoding='utf-8-sig'. Markdown và JSON UTF-8.

## Thay đổi V2
Giữ nguyên mọi dòng dữ liệu V1 và 8 tài liệu cũ; thêm 15 khách hàng, 32 hợp đồng, 50 dự án, 2 phòng ban, 250 dòng tài chính và 62 tài liệu. Giữ 20 câu hỏi cũ nhưng cập nhật Q03, Q04, Q13 vì tập dữ liệu thay đổi; thêm Q21–Q50. Tất cả 60 dự án có ít nhất một tài liệu liên kết. Tài liệu mới là mô phỏng có cấu trúc và nhiều tình huống, không phải văn bản thực; không dùng để kết luận hiệu năng production. `reference_checks.json` chỉ phục vụ kiểm thử, không index vào RAG hoặc thực thi từ AI.
