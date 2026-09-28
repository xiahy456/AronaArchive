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

#ifndef OPACITYANIMATION_H
#define OPACITYANIMATION_H

#include <QFrame>
#include <QGraphicsOpacityEffect>
#include <QPropertyAnimation>

class OpacityAnimation
{
public:
    OpacityAnimation(QWidget* widget, double opacity, int duration, QEasingCurve easingCurve);

    // 初始化不透明度，初始化动画
    void startAnimation(double start_opacity, double goal_opacity);
    // 直接设置不透明度
	void setOpacity(double opacity);

    // 控件对象指针
	QWidget* m_widget = nullptr;
    // 不透明度效果对象
    QGraphicsOpacityEffect* m_opacityEffect = nullptr;
    // 动画对象
    QPropertyAnimation* m_animation_obj = nullptr;
};

#endif // OPACITYANIMATION_H
