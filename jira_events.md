# Danh sách các sự kiện Jira hỗ trợ

Dưới đây là danh sách các sự kiện Jira phổ biến mà bạn có thể sử dụng để mở rộng ứng dụng:

## Sự kiện liên quan đến Issue

- `jira:issue_created` - Khi issue mới được tạo
- `jira:issue_updated` - Khi issue được cập nhật
- `jira:issue_deleted` - Khi issue bị xóa

## Sự kiện liên quan đến Comment

- `comment_created` - Khi bình luận mới được tạo
- `comment_updated` - Khi bình luận được cập nhật
- `comment_deleted` - Khi bình luận bị xóa

## Sự kiện liên quan đến Trạng thái

- `issue_property_set` - Khi thuộc tính issue được đặt
- `issue_property_deleted` - Khi thuộc tính issue bị xóa

## Sự kiện liên quan đến Sprint

- `sprint_created` - Khi sprint mới được tạo
- `sprint_updated` - Khi sprint được cập nhật
- `sprint_deleted` - Khi sprint bị xóa
- `sprint_started` - Khi sprint bắt đầu
- `sprint_closed` - Khi sprint kết thúc

## Sự kiện liên quan đến Version

- `jira:version_released` - Khi phiên bản được phát hành
- `jira:version_unreleased` - Khi phiên bản bị hủy phát hành
- `jira:version_created` - Khi phiên bản mới được tạo
- `jira:version_deleted` - Khi phiên bản bị xóa
- `jira:version_updated` - Khi phiên bản được cập nhật

## Cách sử dụng trong ứng dụng

Để thêm xử lý cho các sự kiện mới, hãy mở rộng hàm `jira_webhook()` trong file `app.py`:

```python
@app.route('/webhook/jira', methods=['POST'])
def jira_webhook():
    # ... code xác thực ...
    
    event_data = request.json
    webhook_event = event_data.get('webhookEvent')
    
    if webhook_event == 'jira:issue_created':
        handle_issue_created(event_data)
    elif webhook_event == 'jira:issue_updated':
        handle_issue_updated(event_data)
    elif webhook_event == 'comment_created':
        handle_comment_created(event_data)
    elif webhook_event == 'sprint_started':
        handle_sprint_started(event_data)
    # ...và các sự kiện khác
    
    return jsonify({"status": "success"}), 200
```

Sau đó tạo các hàm xử lý tương ứng cho mỗi sự kiện.