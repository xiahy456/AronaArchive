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

#ifndef SPINEMOUSECONTROLLER_H
#define SPINEMOUSECONTROLLER_H

#include <QObject>
#include <QPointF>
#include <QTimer>
#include <QElapsedTimer>
#include <memory>
#include "spine/Skeleton.h"
#include "spine/Bone.h"
#include "spine/AnimationState.h"

class SpineMouseController : public QObject
{
    Q_OBJECT

public:
    explicit SpineMouseController(QObject* parent = nullptr);
    ~SpineMouseController();

    // 初始化控制器
    void initialize(spine::Skeleton* skeleton, spine::AnimationState* animationState,
        const QString& touchBoneName, const QString& headAnimationPrefix = "Pat_01", const QString& headAnimationEndPrefix = "PatEnd_01");

    // 鼠标事件处理
    void handleMousePress(const QPointF& globalPos, const QPointF& localPos,
        float spineX, float spineY, float scale);
    void handleMouseRelease(const QPointF& globalPos);
    void handleMouseMove(const QPointF& globalPos, const QPointF& localPos,
        float spineX, float spineY, float scale);

    // 设置参数
    void setEyeRadius(float radius) { m_eyeRadius = radius; }
    void setLinearAlgebraScale(float scale) { m_linearAlgebraScale = scale; }
    void setMouseTracking(bool enabled) { m_mouseTracking = enabled; }
    void setPenetration(bool enabled) { m_penetration = enabled; }
    void setMouseTrial(bool enabled) { m_mouseTrial = enabled; }
    void setLongTouchInterval(int ms) { m_longTouchTimer.setInterval(ms); }

    // 头部动画名称设置
    void setHeadAnimationNames(const QString& touch, const QString& end) {
        m_headAnimation = touch;
        m_headAnimationEnd = end;
    }

    // 获取当前鼠标局部坐标（用于眼睛追踪）
    QPointF getMouseLocalPoint() const { return m_state.mouseLocalPoint; }

signals:
    void talkTriggered(int index);  // 触发对话信号
    void headTouched(bool touched); // 头部触摸状态改变信号
    void longTouchTriggered(bool isLongTouch); // 长按触发信号

private slots:
    void onLongTouchTimeout();
    void onUpdateEyes();

private:
    struct State {
        bool mouseDown = false;           // 鼠标是否按下
        bool isAnimation = false;          // 是否正在播放动画
        int talkIndex = 1;                 // 对话索引
        bool isInterval = false;            // 是否在间隔中
        bool longTouch = false;             // 是否长按
        bool patHead = false;               // 是否触摸头部
        QPointF touchBonePoint;             // 触摸骨骼点
        QPointF mouseLocalPoint;             // 鼠标局部坐标
        float linearAlgebraScale = 1.1f;     // 线性代数缩放
        int talkCount = 0;                   // 对话计数
    } m_state;

    // Spine相关指针
    spine::Skeleton* m_skeleton = nullptr;
    spine::AnimationState* m_animationState = nullptr;
    spine::Bone* m_touchBone = nullptr;

    QString m_touchBoneName;
    QString m_headAnimation;
    QString m_headAnimationEnd;

    // 配置参数
    float m_eyeRadius = 400.0f;
    float m_linearAlgebraScale = 1.1f;
    bool m_mouseTracking = true;
    bool m_penetration = true;
    bool m_mouseTrial = true;

    // 定时器
    QTimer m_longTouchTimer;
    QTimer m_updateTimer;

    // 辅助函数
    QPointF worldToLocal(const QPointF& worldPoint, float spineX, float spineY, float scale);
    QPointF localToBone(const QPointF& localPoint);
    float vectorLength(const QPointF& vec) const;
    QPointF clampVectorLength(const QPointF& vec, float maxLength) const;
    bool isPointNearHead(const QPointF& point, float scale) const;
    QPointF screenToSpineWorld(const QPointF& screenPoint, float spineX, float spineY, float scale);

    // 播放动画
    void playHeadAnimation(bool isTouch);
    void playHeadAnimationEnd();
};

#endif // SPINEMOUSECONTROLLER_H