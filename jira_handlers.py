import os
from datetime import datetime, timedelta

# Xử lý các loại sự kiện Jira khác nhau và gửi thông báo tới Discord
# File này có thể được import vào app.py để mở rộng chức năng

def handle_comment_created(event_data, send_discord_notification):
    """
    Xử lý sự kiện khi có bình luận mới được tạo
    """
    comment = event_data.get('comment', {})
    issue = event_data.get('issue', {})

    if not comment or not issue:
        return

    issue_key = issue.get('key')
    issue_summary = issue.get('fields', {}).get('summary')
    comment_body = comment.get('body')
    comment_author = comment.get('author', {}).get('displayName')

    # Giới hạn độ dài của nội dung comment để hiển thị
    if len(comment_body) > 200:
        comment_body = comment_body[:197] + "..."

    # Chuẩn bị dữ liệu cho thông báo Discord
    fields = [
        {"name": "Issue", "value": issue_key, "inline": True},
        {"name": "Người bình luận", "value": comment_author, "inline": True},
        {"name": "Nội dung", "value": comment_body, "inline": False},
        {"name": "Link", "value": f"{os.getenv('JIRA_URL')}/browse/{issue_key}", "inline": False}
    ]

    title = f"💬 Bình luận mới trên issue: {issue_key}"
    description = f"**{issue_summary}**"

    # Gửi thông báo đến Discord (màu xanh dương nhạt)
    send_discord_notification(title, description, 3066993, fields)


def handle_sprint_started(event_data, send_discord_notification):
    """
    Xử lý sự kiện khi một sprint được bắt đầu
    """
    sprint = event_data.get('sprint', {})

    if not sprint:
        return

    sprint_name = sprint.get('name')
    sprint_goal = sprint.get('goal', 'Không có mục tiêu')
    sprint_start_date = sprint.get('startDate')
    sprint_end_date = sprint.get('endDate')

    # Định dạng lại ngày nếu có
    if sprint_start_date:
        start_date = datetime.fromisoformat(sprint_start_date.replace('Z', '+00:00'))
        sprint_start_date = start_date.strftime('%d/%m/%Y')

    if sprint_end_date:
        end_date = datetime.fromisoformat(sprint_end_date.replace('Z', '+00:00'))
        sprint_end_date = end_date.strftime('%d/%m/%Y')

    # Chuẩn bị dữ liệu cho thông báo Discord
    fields = [
        {"name": "Sprint Goal", "value": sprint_goal, "inline": False},
        {"name": "Ngày bắt đầu", "value": sprint_start_date, "inline": True},
        {"name": "Ngày kết thúc", "value": sprint_end_date, "inline": True},
        {"name": "Link",
         "value": f"{os.getenv('JIRA_URL')}/secure/RapidBoard.jspa?rapidView={sprint.get('originBoardId')}",
         "inline": False}
    ]

    title = f"🏃‍♂️ Sprint mới đã bắt đầu: {sprint_name}"
    description = "Sprint đã bắt đầu và cần được theo dõi tiến độ."

    # Gửi thông báo đến Discord (màu xanh lá)
    send_discord_notification(title, description, 5763719, fields)


def handle_overdue_task_assigned(issue_data, send_discord_notification):
    """
    Xử lý thông báo khi task được gán cho một người nhưng sắp đến hạn
    """
    issue_key = issue_data.get('key')
    summary = issue_data.get('fields', {}).get('summary')
    due_date = issue_data.get('fields', {}).get('duedate')
    assignee = issue_data.get('fields', {}).get('assignee', {}).get('displayName', 'Chưa gán')
    priority = issue_data.get('fields', {}).get('priority', {}).get('name', 'Không xác định')

    # Chuẩn bị dữ liệu cho thông báo Discord
    fields = [
        {"name": "Người được gán", "value": assignee, "inline": True},
        {"name": "Deadline", "value": due_date, "inline": True},
        {"name": "Độ ưu tiên", "value": priority, "inline": True},
        {"name": "Link", "value": f"{os.getenv('JIRA_URL')}/browse/{issue_key}", "inline": False}
    ]

    title = f"⏰ Task sắp đến hạn: {issue_key}"
    description = f"**{summary}**"

    # Gửi thông báo đến Discord (màu cam)
    send_discord_notification(title, description, 15105570, fields)


def handle_high_priority_issue(issue_data, send_discord_notification):
    """
    Xử lý thông báo khi có issue độ ưu tiên cao được tạo
    """
    issue_key = issue_data.get('key')
    summary = issue_data.get('fields', {}).get('summary')
    priority = issue_data.get('fields', {}).get('priority', {}).get('name')
    reporter = issue_data.get('fields', {}).get('reporter', {}).get('displayName')
    issue_type = issue_data.get('fields', {}).get('issuetype', {}).get('name')

    # Chuẩn bị dữ liệu cho thông báo Discord
    fields = [
        {"name": "Loại issue", "value": issue_type, "inline": True},
        {"name": "Mức ưu tiên", "value": priority, "inline": True},
        {"name": "Người báo cáo", "value": reporter, "inline": True},
        {"name": "Link", "value": f"{os.getenv('JIRA_URL')}/browse/{issue_key}", "inline": False}
    ]

    title = f"🔴 Issue ưu tiên cao: {issue_key}"
    description = f"**{summary}**"

    # Gửi thông báo đến Discord (màu đỏ)
    send_discord_notification(title, description, 15158332, fields)


def check_upcoming_deadlines(jira_api, days=3, send_discord_notification=None):
    """
    Kiểm tra và thông báo các task sắp đến hạn trong số ngày quy định
    """
    if not jira_api or not send_discord_notification:
        return

    # Tính ngày hiện tại và ngày tương lai
    today = datetime.now().strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")

    # JQL query để tìm task sắp đến hạn
    jql = f'duedate >= "{today}" AND duedate <= "{future}" AND resolution = Unresolved'

    try:
        response = jira_api.search_issues(jql)

        for issue in response.issues:
            issue_data = {
                'key': issue.key,
                'fields': {
                    'summary': issue.fields.summary,
                    'duedate': issue.fields.duedate,
                    'assignee': {
                        'displayName': issue.fields.assignee.displayName if issue.fields.assignee else 'Unassigned'},
                    'priority': {'name': issue.fields.priority.name if issue.fields.priority else 'Unknown'}
                }
            }

            handle_overdue_task_assigned(issue_data, send_discord_notification)

    except Exception as e:
        print(f"Error checking upcoming deadlines: {str(e)}")
