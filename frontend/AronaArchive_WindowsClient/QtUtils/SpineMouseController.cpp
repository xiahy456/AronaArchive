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

#include "SpineMouseController.h"
#include <cmath>
#include <QDebug>

SpineMouseController::SpineMouseController(QObject* parent)
    : QObject(parent)
{
    // 初始化更新定时器（50fps）
    m_updateTimer.setInterval(20);
    connect(&m_updateTimer, &QTimer::timeout, this, &SpineMouseController::onUpdateEyes);
    m_updateTimer.start();

    // 连接长按定时器
    connect(&m_longTouchTimer, &QTimer::timeout, this, &SpineMouseController::onLongTouchTimeout);
    m_longTouchTimer.setSingleShot(true);
    m_longTouchTimer.setInterval(100);
}

SpineMouseController::~SpineMouseController()
{
    m_updateTimer.stop();
    m_longTouchTimer.stop();
}

void SpineMouseController::initialize(spine::Skeleton* skeleton, spine::AnimationState* animationState,
    const QString& touchBoneName, const QString& headAnimationPrefix, const QString& headAnimationEndPrefix)
{
    m_skeleton = skeleton;
    m_animationState = animationState;
    m_touchBoneName = touchBoneName;

    if (m_skeleton) {
        m_touchBone = m_skeleton->findBone(touchBoneName.toStdString().c_str());
        if (m_touchBone) {
            qDebug() << "Found bone:" << touchBoneName
                << "at position:" << m_touchBone->getWorldX()
                << "," << m_touchBone->getWorldY();
        }
    }

    // 设置默认头部动画名称
    m_headAnimation = headAnimationPrefix;
    m_headAnimationEnd = headAnimationPrefix;
}

void SpineMouseController::handleMousePress(const QPointF& globalPos, const QPointF& localPos,
    float spineX, float spineY, float scale)
{
    if (!m_touchBone) {
        qWarning() << "Touch bone not found!";
        return;
    }

    m_state.mouseDown = true;

    // 计算鼠标在Spine世界中的坐标
    QPointF spineWorldPoint = screenToSpineWorld(globalPos, spineX, spineY, scale);

    // 获取骨骼的世界位置
    float boneX = m_touchBone->getWorldX();
    float boneY = m_touchBone->getWorldY();

    qDebug() << "=== Mouse Press Debug in Controller ===";
    qDebug() << "Bone world position:" << boneX << "," << boneY;
    qDebug() << "Mouse world point:" << spineWorldPoint.x() << "," << spineWorldPoint.y();

    // 计算相对于骨骼的偏移（用于判断触摸）
    float dx = spineWorldPoint.x() - boneX;
    float dy = spineWorldPoint.y() - boneY;
    float distance = std::sqrt(dx * dx + dy * dy);

    qDebug() << "Offset from bone:" << dx << "," << dy;
    qDebug() << "Distance to bone:" << distance;

    // 判断是否触摸到头部
    m_state.patHead = distance <= (400.0f * scale);
    emit headTouched(m_state.patHead);

    // 设置鼠标位置（使用相对于骨骼的偏移，而不是绝对世界坐标）
    m_state.mouseLocalPoint = QPointF(dx, dy);

    qDebug() << "Mouse local offset:" << dx << "," << dy;
    qDebug() << "Head touched:" << m_state.patHead;
}

void SpineMouseController::handleMouseRelease(const QPointF& globalPos)
{
    // 停止长按定时器
    m_longTouchTimer.stop();

    // 如果不是长按且启用了穿透，触发对话
    if (!m_state.longTouch && m_penetration) {
        emit talkTriggered(m_state.talkIndex);
        m_state.talkCount++;
    }

    // 如果触摸到头部且是长按且没有正在播放动画，播放头部动画结束
    if (m_state.patHead && m_state.longTouch && !m_state.isAnimation) {
        playHeadAnimationEnd();
    }

    // 重置状态
    m_state.mouseLocalPoint = QPointF(0, 0);
    m_state.mouseDown = false;
    m_state.longTouch = false;
    m_state.patHead = false;
    emit headTouched(false);
    emit longTouchTriggered(false);
}

void SpineMouseController::handleMouseMove(const QPointF& globalPos, const QPointF& localPos,
    float spineX, float spineY, float scale)
{
    if (!m_touchBone) return;

    // 鼠标追踪或长按时更新眼睛注视点
    if (m_mouseTracking || m_state.longTouch) {
        // 计算鼠标在Spine世界中的坐标
        QPointF spineWorldPoint = screenToSpineWorld(globalPos, spineX, spineY, scale);
        m_state.mouseLocalPoint = spineWorldPoint;
    }
}

void SpineMouseController::onLongTouchTimeout()
{
    if (!m_state.mouseDown) return;

    m_state.longTouch = true;
    emit longTouchTriggered(true);

    // 如果触摸到头部且没有正在播放动画，播放头部动画
    if (m_state.patHead && !m_state.isAnimation) {
        playHeadAnimation(true);
    }
}

void SpineMouseController::onUpdateEyes()
{
    if (!m_touchBone || !m_skeleton) return;

    // 获取骨骼当前位置（局部坐标）
    float boneX = m_touchBone->getX();
    float boneY = m_touchBone->getY();

    // 目标位置是相对于骨骼的偏移
    QPointF targetOffset = m_state.mouseLocalPoint;

    // 限制移动范围
    targetOffset = clampVectorLength(targetOffset, m_eyeRadius);

    // 平滑移动 - 直接设置偏移
    float newX = targetOffset.x();
    float newY = targetOffset.y();

    // 只有当变化足够大时才更新
    if (std::abs(boneX - newX) > 0.1f || std::abs(boneY - newY) > 0.1f) {
        m_touchBone->setX(newX);
        m_touchBone->setY(newY);

        // 更新骨骼世界变换
        m_skeleton->updateWorldTransform(spine::Physics_Update);

        qDebug() << "Updating bone - Old:" << boneX << "," << boneY
            << "New:" << newX << "," << newY;
    }
}

QPointF SpineMouseController::screenToSpineWorld(const QPointF& screenPoint,
    float spineX, float spineY, float scale)
{
    // 计算相对于Spine原点的偏移
    float dx = screenPoint.x() - spineX;
    float dy = screenPoint.y() - spineY;

    // 应用缩放并翻转Y轴
    QPointF result;
    result.setX(dx / scale);
    result.setY(-dy / scale);  // 负号因为屏幕Y向下，Spine Y向上

    qDebug() << "ScreenToSpineWorld -"
        << "Screen:" << screenPoint.x() << "," << screenPoint.y()
        << "SpineOrigin:" << spineX << "," << spineY
        << "Offset:" << dx << "," << dy
        << "Scale:" << scale
        << "Result:" << result.x() << "," << result.y();

    return result;
}

float SpineMouseController::vectorLength(const QPointF& vec) const
{
    return std::sqrt(vec.x() * vec.x() + vec.y() * vec.y());
}

QPointF SpineMouseController::clampVectorLength(const QPointF& vec, float maxLength) const
{
    float length = vectorLength(vec);
    if (length > maxLength && length > 0) {
        float scale = maxLength / length;
        return QPointF(vec.x() * scale, vec.y() * scale);
    }
    return vec;
}

bool SpineMouseController::isPointNearHead(const QPointF& point, float scale) const
{
    if (!m_touchBone) return false;

    // 获取骨骼的世界位置
    float boneX = m_touchBone->getWorldX();
    float boneY = m_touchBone->getWorldY();

    // 计算点到骨骼的距离
    float dx = point.x() - boneX;
    float dy = point.y() - boneY;
    float distance = std::sqrt(dx * dx + dy * dy);

    qDebug() << "Distance check - Point:" << point.x() << "," << point.y()
        << "Bone:" << boneX << "," << boneY
        << "Distance:" << distance
        << "Threshold:" << (400.0f * scale);

    return distance <= (400.0f * scale);
}

void SpineMouseController::playHeadAnimation(bool isTouch)
{
    if (!m_animationState) return;

    m_state.isAnimation = true;

    std::string animA = (m_headAnimation + "_A").toStdString();
    std::string animM = (m_headAnimation + "_M").toStdString();

    m_animationState->setAnimation(5, animA.c_str(), false);
    m_animationState->setAnimation(6, animM.c_str(), false);
}

void SpineMouseController::playHeadAnimationEnd()
{
    if (!m_animationState) return;

    std::string animA = (m_headAnimationEnd + "_A").toStdString();
    std::string animM = (m_headAnimationEnd + "_M").toStdString();

    m_animationState->setAnimation(5, animA.c_str(), false);
    m_animationState->setAnimation(6, animM.c_str(), false);

    m_state.isAnimation = false;
}