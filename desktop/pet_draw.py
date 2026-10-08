"""Q 版小猫绘制：QPainter 程序绘制，无外部素材。状态：idle/alert/happy/sad/talk"""
import math

from PySide6.QtCore import QPointF, QPoint, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPen, QPolygon,
                           QPainterPath)


def draw_pet(painter: QPainter, state: str, tick: int, w: int = 150, h: int = 150):
    """tick 为全局动画帧计数（每 50ms +1），用于呼吸/摆动"""
    painter.setRenderHint(QPainter.Antialiasing)
    cx, cy = w / 2, h / 2

    # 呼吸浮动
    bob = math.sin(tick / 12) * 3 if state == "idle" else math.sin(tick / 5) * 2
    bounce = abs(math.sin(tick / 4)) * 8 if state == "alert" else 0
    body_y = cy + 15 - bob - bounce

    # 情绪配色
    body_color = QColor("#f7d794")          # 奶黄
    if state == "happy":
        body_color = QColor("#ffd6e0")
    elif state == "sad":
        body_color = QColor("#c8d6e5")
    elif state == "alert":
        body_color = QColor("#ffe0b2")

    # ---- 尾巴（摆动）----
    tail_swing = math.sin(tick / 8) * 14
    painter.setPen(QPen(QColor("#e8b04b"), 5, Qt.SolidLine, Qt.RoundCap))
    painter.drawArc(QRectF(cx + 18, body_y - 28, 34, 30),
                    int(-30 * 16), int((90 + tail_swing) * 16))

    # ---- 身体 ----
    painter.setPen(QPen(QColor("#8d6e3a"), 2))
    painter.setBrush(QBrush(body_color))
    painter.drawEllipse(QPointF(cx, body_y), 34, 28)

    # ---- 头 ----
    head_y = body_y - 38
    painter.drawEllipse(QPointF(cx, head_y), 30, 26)

    # ---- 耳朵（三角，警觉时竖高）----
    ear_h = 16 if state != "alert" else 22
    painter.setBrush(QBrush(body_color))
    for sx in (-1, 1):
        ear = QPolygon([
            QPoint(int(cx + sx * 20), int(head_y - 16)),
            QPoint(int(cx + sx * 27), int(head_y - 16 - ear_h)),
            QPoint(int(cx + sx * 9), int(head_y - 24)),
        ])
        painter.drawPolygon(ear)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#ffaaa5")))
        painter.drawPolygon(QPolygon([
            QPoint(int(cx + sx * 18), int(head_y - 17)),
            QPoint(int(cx + sx * 23), int(head_y - 15 - ear_h + 6)),
            QPoint(int(cx + sx * 12), int(head_y - 21)),
        ]))
        painter.setPen(QPen(QColor("#8d6e3a"), 2))
        painter.setBrush(QBrush(body_color))

    # ---- 眼睛（眨眼：tick 周期闭合）----
    blink = (tick % 160) < 8
    eye_color = QColor("#37474f")
    painter.setPen(Qt.NoPen)
    if state == "sad":
        painter.setBrush(QBrush(eye_color))
        painter.drawEllipse(QPointF(cx - 11, head_y - 2), 3.5, 5)
        painter.drawEllipse(QPointF(cx + 11, head_y - 2), 3.5, 5)
        # 泪滴
        painter.setBrush(QBrush(QColor("#74b9ff")))
        tear_y = head_y + 6 + (tick % 40) / 40 * 8
        painter.drawEllipse(QPointF(cx + 13, tear_y), 2.5, 3.5)
    elif blink:
        painter.setPen(QPen(eye_color, 2))
        painter.drawLine(QPointF(cx - 14, head_y - 2), QPointF(cx - 8, head_y - 2))
        painter.drawLine(QPointF(cx + 8, head_y - 2), QPointF(cx + 14, head_y - 2))
        painter.setPen(Qt.NoPen)
    else:
        painter.setBrush(QBrush(eye_color))
        painter.drawEllipse(QPointF(cx - 11, head_y - 2), 4, 5)
        painter.drawEllipse(QPointF(cx + 11, head_y - 2), 4, 5)
        # 高光
        painter.setBrush(QBrush(Qt.white))
        painter.drawEllipse(QPointF(cx - 12, head_y - 4), 1.4, 1.6)
        painter.drawEllipse(QPointF(cx + 10, head_y - 4), 1.4, 1.6)

    # ---- 鼻子和嘴 ----
    painter.setBrush(QBrush(QColor("#e17055")))
    painter.drawEllipse(QPointF(cx, head_y + 6), 2.5, 2)
    painter.setPen(QPen(QColor("#8d6e3a"), 1.6))
    if state == "happy" or state == "alert":
        path = QPainterPath(QPointF(cx - 6, head_y + 10))
        path.quadTo(QPointF(cx, head_y + 15), QPointF(cx + 6, head_y + 10))
        painter.drawPath(path)
    elif state == "sad":
        path = QPainterPath(QPointF(cx - 5, head_y + 13))
        path.quadTo(QPointF(cx, head_y + 9), QPointF(cx + 5, head_y + 13))
        painter.drawPath(path)
    else:
        painter.drawLine(QPointF(cx, head_y + 8), QPointF(cx, head_y + 11))
        painter.drawLine(QPointF(cx - 3, head_y + 11), QPointF(cx, head_y + 11))
        painter.drawLine(QPointF(cx, head_y + 11), QPointF(cx + 3, head_y + 11))

    # ---- 胡须 ----
    painter.setPen(QPen(QColor(141, 110, 58, 140), 1.2))
    for sx in (-1, 1):
        painter.drawLine(QPointF(cx + sx * 12, head_y + 5), QPointF(cx + sx * 26, head_y + 3))
        painter.drawLine(QPointF(cx + sx * 12, head_y + 8), QPointF(cx + sx * 26, head_y + 9))

    # ---- 状态气泡 ----
    painter.setPen(QPen(QColor("#606266"), 1))
    painter.setBrush(QBrush(QColor(255, 255, 255, 230)))
    bubble = QRectF(cx + 30, head_y - 46, 64, 26)
    painter.drawRoundedRect(bubble, 6, 6)
    painter.setPen(QColor("#303133"))
    painter.setFont(QFont("Microsoft YaHei", 8, QFont.Bold))
    bubble_text = {
        "idle": "盯盘中..",
        "alert": "有情况!",
        "happy": "赚啦!",
        "sad": "呜..熔断",
        "talk": "在听..",
    }.get(state, "")
    painter.drawText(bubble, Qt.AlignCenter, bubble_text)
