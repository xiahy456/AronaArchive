/*
 Copyright 2026 xia_hy456. All rights reserved.

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

      https://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
*/

#include "ParallelogramButton.h"
#include <QPainterPath>

ParallelogramButton::ParallelogramButton(QWidget* parent)
    : QPushButton(parent)
    , m_shear(0.5774)
    , m_fillColor(255, 255, 255)
    , m_hoverColor(245, 245, 245)
    , m_pressedColor(232, 232, 232)
    , m_isHovered(false)
    , m_isPressed(false)
    , m_hasBackgroundImage(false)
    , m_imageScaleMode(Qt::IgnoreAspectRatio)  // 默认裁剪模式
{
    setFixedSize(150, 50);
    setCursor(Qt::PointingHandCursor);
    setFlat(true);  // 设置为扁平样式，去掉默认边框
    setAttribute(Qt::WA_StyledBackground, true);
}

void ParallelogramButton::setShearValue(qreal shear)
{
    m_shear = shear;
    update();
}

void ParallelogramButton::setFillColor(const QColor& color)
{
    m_fillColor = color;
    update();
}

void ParallelogramButton::setHoverColor(const QColor& color)
{
    m_hoverColor = color;
    update();
}

void ParallelogramButton::setPressedColor(const QColor& color)
{
    m_pressedColor = color;
    update();
}

void ParallelogramButton::setBackgroundImage(const QString& imagePath)
{
    QPixmap pixmap(imagePath);
    if (!pixmap.isNull()) {
        m_backgroundImage = pixmap;
        m_hasBackgroundImage = true;
        update();
    }
}

void ParallelogramButton::setBackgroundImage(const QPixmap& pixmap)
{
    if (!pixmap.isNull()) {
        m_backgroundImage = pixmap;
        m_hasBackgroundImage = true;
        update();
    }
}

void ParallelogramButton::setImageScaleMode(Qt::AspectRatioMode mode)
{
    m_imageScaleMode = mode;
    update();
}

void ParallelogramButton::setTextColor(const QColor& color)
{
    m_textColor = color;
    update();  // 触发重绘
}

void ParallelogramButton::setBorderWidth(int width)
{
    m_borderWidth = width;
	update();
}

void ParallelogramButton::paintEvent(QPaintEvent* event)
{
    Q_UNUSED(event);

    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);  // 抗锯齿

    // 创建平行四边形路径
    QPainterPath path;
    int width = this->width();
    int height = this->height();
    int offset = static_cast<int>(height * m_shear);  // 倾斜偏移量

    // 定义四个顶点（按顺序）
    QPointF topLeft(offset, 0);
    QPointF topRight(width, 0);
    QPointF bottomRight(width - offset, height);
    QPointF bottomLeft(0, height);

    path.moveTo(topLeft);
    path.lineTo(topRight);
    path.lineTo(bottomRight);
    path.lineTo(bottomLeft);
    path.closeSubpath();

    // 根据状态选择颜色
    QColor currentColor;
    if (m_isPressed) {
        currentColor = m_pressedColor;
    }
    else if (m_isHovered) {
        currentColor = m_hoverColor;
    }
    else {
        currentColor = m_fillColor;
    }

    // 绘制背景
    if (m_hasBackgroundImage && !m_backgroundImage.isNull()) {
        // 方法1：使用图片作为背景填充
        painter.save();
        painter.setClipPath(path);  // 设置裁剪区域为平行四边形

        // 缩放图片以适应控件大小
        QPixmap scaledPixmap;
        if (m_imageScaleMode == Qt::IgnoreAspectRatio) {
            // 拉伸填充
            scaledPixmap = m_backgroundImage.scaled(width, height,
                Qt::IgnoreAspectRatio,
                Qt::SmoothTransformation);
        }
        else {
            // 保持比例
            scaledPixmap = m_backgroundImage.scaled(width, height,
                m_imageScaleMode,
                Qt::SmoothTransformation);
        }

        painter.drawPixmap(0, 0, scaledPixmap);
        painter.restore();

        // 可选：在图片上叠加半透明遮罩（根据按钮状态）
        QColor overlayColor;
        if (m_isPressed) {
            overlayColor = QColor(0, 0, 0, 80);  // 按下时变暗
        }
        else if (m_isHovered) {
            overlayColor = QColor(255, 255, 255, 50);  // 悬停时变亮
        }

        if (overlayColor.isValid()) {
            painter.fillPath(path, overlayColor);
        }
    }
    else {
        // 使用纯色填充（原有逻辑）
        QColor currentColor;
        if (m_isPressed) {
            currentColor = m_pressedColor;
        }
        else if (m_isHovered) {
            currentColor = m_hoverColor;
        }
        else {
            currentColor = m_fillColor;
        }
        painter.fillPath(path, currentColor);
    }

    // 绘制边框
    if (m_borderWidth) {
        QPen leftPen(QColor(147, 230, 255), m_borderWidth);  // 浅蓝色，粗4
        painter.setPen(leftPen);
        painter.drawLine(bottomLeft, topLeft);
    }

    // 绘制文字
    painter.setPen(m_textColor);
    QFont font = painter.font();
    //font.setBold(true); // 粗体
    painter.setFont(font);
    painter.drawText(rect(), Qt::AlignCenter, text());
}

void ParallelogramButton::enterEvent(QEnterEvent* event)
{
    m_isHovered = true;
    update();
    QPushButton::enterEvent(event);
}

void ParallelogramButton::leaveEvent(QEvent* event)
{
    m_isHovered = false;
    update();
    QPushButton::leaveEvent(event);
}

void ParallelogramButton::mousePressEvent(QMouseEvent* event)
{
    m_isPressed = true;
    update();
    QPushButton::mousePressEvent(event);
}

void ParallelogramButton::mouseReleaseEvent(QMouseEvent* event)
{
    m_isPressed = false;
    update();
    QPushButton::mouseReleaseEvent(event);
}