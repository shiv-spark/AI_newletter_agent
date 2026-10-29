"""Subscription management endpoints (subscribe / unsubscribe)."""
import html

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.config import settings
from app.database.db import SessionLocal
from app.database.models import User
from app.services.token_service import verify_user_token

router = APIRouter(tags=["subscriptions"])

UNSUBSCRIBE_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Unsubscribed · {brand}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #063024;
      color: #e5e7eb;
      margin: 0;
      padding: 40px 16px;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 80vh;
    }}
    .card {{
      background: #094333;
      border: 1px solid rgba(52, 211, 153, 0.2);
      border-radius: 12px;
      padding: 36px 28px;
      max-width: 460px;
      width: 100%;
      text-align: center;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
    }}
    h1 {{
      font-size: 22px;
      margin: 0 0 12px;
      color: #34d399;
    }}
    p {{
      color: #9ca3af;
      font-size: 15px;
      line-height: 1.5;
      margin: 0 0 24px;
    }}
    .btn {{
      display: inline-block;
      background: #10b981;
      color: #063024;
      text-decoration: none;
      font-weight: 600;
      padding: 11px 22px;
      border-radius: 8px;
      font-size: 14px;
      transition: background 0.15s ease;
    }}
    .btn:hover {{
      background: #34d399;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>You have unsubscribed</h1>
    <p>You will no longer receive the <strong>{brand}</strong> newsletter at <strong>{email}</strong>.</p>
    <a href="/subscribe?token={token}" class="btn">Resubscribe</a>
  </div>
</body>
</html>"""

SUBSCRIBE_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Subscribed · {brand}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #063024;
      color: #e5e7eb;
      margin: 0;
      padding: 40px 16px;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 80vh;
    }}
    .card {{
      background: #094333;
      border: 1px solid rgba(52, 211, 153, 0.2);
      border-radius: 12px;
      padding: 36px 28px;
      max-width: 460px;
      width: 100%;
      text-align: center;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
    }}
    h1 {{
      font-size: 22px;
      margin: 0 0 12px;
      color: #34d399;
    }}
    p {{
      color: #9ca3af;
      font-size: 15px;
      line-height: 1.5;
      margin: 0 0 24px;
    }}
    .btn {{
      display: inline-block;
      background: #10b981;
      color: #063024;
      text-decoration: none;
      font-weight: 600;
      padding: 11px 22px;
      border-radius: 8px;
      font-size: 14px;
      transition: background 0.15s ease;
    }}
    .btn:hover {{
      background: #34d399;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Welcome back!</h1>
    <p>Your subscription is active again for <strong>{email}</strong>. You will receive upcoming editions of <strong>{brand}</strong>.</p>
    <a href="/unsubscribe?token={token}" style="color:#9ca3af;font-size:13px;text-decoration:underline;">Unsubscribe again</a>
  </div>
</body>
</html>"""


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str = Query(..., description="Signed user token")):
    user_id = verify_user_token(token)
    if not user_id:
        raise HTTPException(
            status_code=400, detail="Invalid or expired unsubscribe link."
        )

    with SessionLocal() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        user.is_active = False
        session.commit()
        email = user.email

    brand = settings.newsletter_brand or "AI Newsletter"
    page = UNSUBSCRIBE_PAGE.format(
        brand=html.escape(brand),
        email=html.escape(email),
        token=html.escape(token),
    )
    return HTMLResponse(page)


@router.get("/subscribe", response_class=HTMLResponse)
def subscribe(token: str = Query(..., description="Signed user token")):
    user_id = verify_user_token(token)
    if not user_id:
        raise HTTPException(
            status_code=400, detail="Invalid or expired subscribe link."
        )

    with SessionLocal() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        user.is_active = True
        session.commit()
        email = user.email

    brand = settings.newsletter_brand or "AI Newsletter"
    page = SUBSCRIBE_PAGE.format(
        brand=html.escape(brand),
        email=html.escape(email),
        token=html.escape(token),
    )
    return HTMLResponse(page)
