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

#include "opacityanimation.h"

OpacityAnimation::OpacityAnimation(QWidget* widget, double opacity, int duration, QEasingCurve easingCurve) {
    // 构建对象
    this->m_opacityEffect = new QGraphicsOpacityEffect;
    this->m_animation_obj = new QPropertyAnimation(m_opacityEffect, "opacity");
    this->m_widget = widget;
    // 绑定对象
    m_widget->setGraphicsEffect(m_opacityEffect);
    // 初始化frame
    setOpacity(opacity);
    // 初始化动画对象
    m_animation_obj->setDuration(duration);   // 动画持续时间
    m_animation_obj->setEasingCurve(easingCurve);    // 缓入缓出效果
}

void OpacityAnimation::startAnimation(double start_opacity, double goal_opacity) {
    this->m_animation_obj->setStartValue(start_opacity);
    this->m_animation_obj->setEndValue(goal_opacity);
    this->m_animation_obj->start();
}

void OpacityAnimation::setOpacity(double opacity)
{
    this->m_opacityEffect->setOpacity(opacity);
    m_widget->setGraphicsEffect(m_opacityEffect);
}
