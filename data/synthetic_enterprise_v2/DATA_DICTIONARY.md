# Từ điển dữ liệu

## Các bảng

| File | Khóa chính | Khóa liên kết | Ý nghĩa |
|---|---|---|---|
| customers.csv | customer_id | – | Khách hàng: tên, lĩnh vực |
| departments.csv | department_id | – | Phòng ban phụ trách |
| contracts.csv | contract_id | customer_id → customers | Tên, ngày ký, hạn dự kiến, giá trị hợp đồng VND |
| projects.csv | project_id | contract_id → contracts; department_id → departments | Tên, trạng thái tại 31/10/2026 |
| project_financials.csv | financial_id | project_id → projects | Tháng (YYYY-MM-01), revenue_vnd, direct_cost_vnd |
| documents.csv | document_id | relative_path → file Markdown | Tiêu đề, loại và đường dẫn tài liệu |
| document_projects.csv | document_id + project_id | documents, projects | Liên kết nhiều-nhiều tài liệu–dự án |

Các mã ID và trường tên/lĩnh vực/loại/trạng thái là chuỗi. Ngày ISO YYYY-MM-DD. Số tiền là số nguyên VND, nên dùng BIGINT nếu lưu SQL. Các khóa liên kết không được rỗng. Mỗi project chỉ có một contract và một department trong POC. Mỗi project có duy nhất một bản ghi tài chính mỗi tháng. Trạng thái: in_progress (đang thực hiện), completed (hoàn thành), on_hold (tạm dừng); loại tài liệu: policy, contract, meeting, acceptance, test_plan. Tài liệu policy không có liên kết dự án riêng, áp dụng chung.

## Công thức KPI

- Doanh thu: SUM(revenue_vnd).
- Chi phí trực tiếp: SUM(direct_cost_vnd).
- Lợi nhuận gộp: SUM(revenue_vnd) − SUM(direct_cost_vnd).
- Tỷ suất lợi nhuận gộp: lợi nhuận gộp / tổng doanh thu × 100; null nếu tổng doanh thu = 0. Không lấy trung bình tỷ suất từng dự án để tính tỷ suất chung.
- So sánh kỳ: giá trị kỳ sau − giá trị kỳ trước; chỉ so sánh các kỳ có dữ liệu.
- Lọc theo khách hàng/phòng ban bằng bảng project/contract. Không cộng contract_value_vnd với doanh thu. Chi phí có thể vượt doanh thu.

## Mô hình Neo4j đề xuất

Nodes: Customer(customer_id), Contract(contract_id), Project(project_id), Department(department_id), Document(document_id). Thuộc tính tên và trạng thái lấy từ CSV. Dùng khóa ID duy nhất cho từng label.

Relationships:
- `(Customer)-[:SIGNED]->(Contract)` từ contracts.customer_id.
- `(Contract)-[:COVERS]->(Project)` từ projects.contract_id.
- `(Department)-[:RESPONSIBLE_FOR]->(Project)` từ projects.department_id.
- `(Project)-[:HAS_DOCUMENT]->(Document)` từ document_projects.csv.

Không tạo quan hệ nhân quả từ các liên kết; graph là projection có thể dựng lại từ CSV, không phải nguồn tính KPI. Tài liệu chính sách dùng tìm kiếm RAG chung, không cần gắn giả tạo vào mọi project. Dùng Cypher template có tham số, chỉ đọc đối với truy vấn AI. Các câu hỏi golden tham chiếu ID thay vì phụ thuộc ngôn ngữ hiển thị.

## Quy mô V2.0
Giữ nguyên schema, ID và kỳ tài chính của V1. Có 6 phòng ban, 60 dự án; mỗi dự án có 5 kỳ tài chính. Tài liệu báo cáo/kiểm thử mới có tình trạng nghiệp vụ tại snapshot 31/10/2026, phụ lục dùng chung theo hợp đồng. `financial_id` và `document_id` vẫn là chuỗi. Không suy ra số tiền đã thu.
