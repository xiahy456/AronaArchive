import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from typing import Dict, List, Optional
import os
import time
from pathlib import Path
import sys
# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from configs import MODEL_CONFIG, TRAINING_CONFIG
from model.aronalm import AronaLM
from data.dataloader import create_data_loader

# 模型训练器
class Trainer:
    def __init__(self, model: AronaLM, config: Dict=None):
        self.model = model
        self.config = config or TRAINING_CONFIG
        # 训练设备
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model.to(self.device)
        print(f"使用设备: {self.device}")
        # 优化器
        self.optimizer = torch.optim.AdamW(
            model.parameters(),
            lr = self.config.learning_rate,
            weight_decay=self.config.weight_decay
        )
        # 学习率调度器
        self.schedule = torch.optim.lr_scheduler.CosineAnnealingLR(
            self.optimizer,
            T_max=self.config.num_epochs
        )
        # 训练历史
        self.train_losses = []
        self.val_losses = []
        # 创建检查点目录
        self.checkpoint_dir = Path(self.config.checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # 训练一个epoch
    def train_epoch(self, dataloader: DataLoader, epoch: int) -> float:
        self.model.train()
        total_loss = 0
        num_batches = len(dataloader)
        for batch_idx, batch in enumerate(dataloader):
            # 数据移动到设备
            input_ids = batch['input_ids'].to(self.device)
            output_ids = batch['output_ids'].to(self.device)
            # 前向传播
            self.optimizer.zero_grad()
            _, loss = self.model(input_ids, output_ids)
            # 反向传播
            loss.backward()
            # 梯度裁剪
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.config.gradient_clip)
            # 优化器步进
            self.optimizer.step()

            total_loss += loss.item()
            
            # 打印进度
            if batch_idx % 10 == 0:
                current_lr = self.optimizer.param_groups[0]['lr']
                print(f'Epoch: {epoch} [{batch_idx}/{num_batches}]'
                      f'Loss: {loss.item():.4f} LR: {current_lr:.6f}')
        
        avg_loss = total_loss / num_batches
        self.train_losses.append(avg_loss)
        return avg_loss
    
    # 验证模型
    def validate(self, dataloader: DataLoader) -> float:
        self.model.eval()
        total_loss = 0
        num_batch = len(dataloader)
        with torch.no_grad():
            for batch in dataloader:
                # input - (output)target
                input_ids = batch['input_ids'].to(self.device)
                output_ids = batch['output_ids'].to(self.device)
                _, loss = self.model(input_ids, output_ids)
                total_loss += loss.item()
        avg_loss = total_loss / num_batch
        self.val_losses.append(avg_loss)
        return avg_loss
    
    # 保存检查点
    def save_checkpoint(self, epoch: int, loss: float):
        checkpoint = {
            'epoch': epoch,
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'schedule_state_dict': self.schedule.state_dict(),
            'train_losses': self.train_losses,
            'val_losses': self.val_losses,
            'config': self.config
        }
        checkpoint_path = self.checkpoint_dir / f'checkpoint_epoch_{epoch}.pt'
        torch.save(checkpoint, checkpoint_path)
        print(f"检查点已保存: {checkpoint_path}")
        # 保存最佳模型
        if loss == min(self.val_losses):
            best_model_path = self.checkpoint_dir / 'best_model.pt'
            torch.save(self.model.state_dict(), best_model_path)
            print(f"最佳模型已保存: {best_model_path}")

    # 完整训练流程
    def train(self,  train_loader: DataLoader, val_loader: DataLoader = None):
        print("开始训练...")
        start_time = time.time()

        for epoch in range(1, self.config.num_epochs + 1):
            epoch_start = time.time()
            # 训练
            train_loss = self.train_epoch(train_loader, epoch)
            # 验证
            val_loss = None
            if val_loader:
                val_loss = self.validate(val_loader)
            # 学习率调度
            self.schedule.step()
            # 打印epoch结果
            epoch_time = time.time()
            current_lr = self.optimizer.param_groups[0]['lr']
            print(f'\nEpoch {epoch} 完成')
            print(f'    训练损失: {train_loss:.4f}')
            if val_loss is not None:
                print(f'    验证损失: {val_loss:.4f}')
            print(f'    学习率: {current_lr}')
            print(f'    耗时: {epoch_time:.2f}秒')
            print('-' * 32)
            # 保存检查点
            if epoch % self.config.checkpoint_save_freq == 0 or epoch == self.config.num_epochs:
                self.save_checkpoint(epoch, val_loss or train_loss)
        
        total_time = time.time() - start_time
        print(f"训练完成！总耗时: {total_time:.2f}秒")
        # 保存最终模型
        final_model_path = self.checkpoint_dir / 'final_model.pt'
        torch.save(self.model.state_dict(), final_model_path)
        print(f"最终模型已保存: {final_model_path}")

# 训练入口主函数
def main():
    print("====    AronaArchive模型训练    ====")
    # 创建模型
    model = AronaLM()
    print(f"模型参数量: {sum(p.numel() for p in model.parameters()):,}")
    # 创建数据加载器
    print("创建数据加载器...")
    train_loader = create_data_loader(
        "raw/training_dialogues.json",
        batch_size=TRAINING_CONFIG.batch_size,
        shuffle=True
    )
    print(f"训练数据批次: {len(train_loader)}")
    # 创建训练器
    trainer = Trainer(model)
    # 开始训练
    trainer.train(train_loader)

    print("训练完成！")

if __name__ == "__main__":
    main()