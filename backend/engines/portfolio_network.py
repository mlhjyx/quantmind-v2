"""Phase 2.1 层2: PortfolioNetwork — 可微分Sharpe Loss Portfolio优化。

层1 LightGBM预测得分 + 因子特征 → 层2 PortfolioMLP → portfolio权重
Loss = -Sharpe + λ × turnover

设计来源: docs/QUANTMIND_FACTOR_UPGRADE_PLAN_V4.md 附录A.1-A.3

核心组件:
  - PortfolioLayer: softmax + clamp + renormalize → 合法权重
  - PortfolioMLP: 3层MLP (input → 64 → 32 → 1) + PortfolioLayer
  - sharpe_loss: 可微分 Sharpe ratio loss + turnover惩罚
  - PortfolioTrainer: 训练循环 (早停 + 梯度裁剪 + L2正则)

注意:
  - 所有操作必须纯PyTorch tensor(可微分)
  - std()接近0时eps=1e-8防梯度爆炸
  - 梯度裁剪 max_norm=1.0
  - 早停 patience=20, 监控validation Sharpe
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F  # noqa: N812
from torch.nn.utils import clip_grad_norm_

# ============================================================
# PortfolioLayer: softmax + clamp + renormalize
# ============================================================


class PortfolioLayer(nn.Module):
    """将raw scores转换为合法portfolio权重。

    约束:
      - 非负 (long-only)
      - 和为1
      - 单只上限 max_weight
    """

    def __init__(self, max_weight: float = 0.10):
        super().__init__()
        self.max_weight = max_weight

    def forward(self, raw_scores: torch.Tensor) -> torch.Tensor:
        """(N,) → (N,) 合法权重。"""
        # ReLU保证非负 → softmax归一化
        positive = F.relu(raw_scores)
        weights = F.softmax(positive, dim=-1)

        # 迭代clamp+renormalize直至收敛(最多5轮)
        for _ in range(5):
            weights = torch.clamp(weights, max=self.max_weight)
            total = weights.sum()
            if total > 0:
                weights = weights / total
            if weights.max() <= self.max_weight + 1e-6:
                break
        return weights


# ============================================================
# PortfolioMLP: LightGBM得分 + 因子特征 → portfolio权重
# ============================================================


class PortfolioMLP(nn.Module):
    """层2 MLP: 输入(lgbm_score, factor_features) → portfolio权重。

    架构: Linear(n_features+1, 64) → ReLU → Dropout(0.3)
           → Linear(64, 32) → ReLU → Linear(32, 1)
           → PortfolioLayer

    Args:
        n_features: 因子特征维度
        hidden: 第一层隐藏单元(默认64)
        max_weight: 单只权重上限(默认0.10)
        dropout: Dropout率(默认0.3)
    """

    def __init__(
        self,
        n_features: int,
        hidden: int = 64,
        max_weight: float = 0.10,
        dropout: float = 0.3,
    ):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_features + 1, hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )
        self.portfolio_layer = PortfolioLayer(max_weight=max_weight)

    def forward(
        self,
        lgbm_scores: torch.Tensor,
        factor_features: torch.Tensor,
    ) -> torch.Tensor:
        """前向传播。

        Args:
            lgbm_scores: (N,) LightGBM预测得分
            factor_features: (N, F) 因子特征矩阵

        Returns:
            (N,) portfolio权重, 和为1
        """
        # 拼接: (N, F+1)
        x = torch.cat([lgbm_scores.unsqueeze(-1), factor_features], dim=-1)
        raw = self.net(x).squeeze(-1)  # (N,)
        return self.portfolio_layer(raw)


# ============================================================
# Sharpe Loss: 可微分
# ============================================================


def sharpe_loss(
    weights_seq: list[torch.Tensor],
    returns_seq: list[torch.Tensor],
    prev_weights_seq: list[torch.Tensor] | None = None,
    cost_rate: float = 0.003,
    lambda_turnover: float = 0.1,
    eps: float = 1e-8,
) -> torch.Tensor:
    """可微分Sharpe loss = -Sharpe + λ × mean_turnover.

    Args:
        weights_seq: 每个调仓日的权重 [(N_t,), ...], T个调仓日
        returns_seq: 每个调仓日到下次调仓日的个股收益 [(N_t,), ...]
        prev_weights_seq: 上一期权重(用于turnover计算), None则假设首期从现金开始
        cost_rate: 单边交易成本率(默认30bps)
        lambda_turnover: turnover惩罚系数
        eps: 防止除以0

    Returns:
        scalar loss tensor
    """
    portfolio_returns = []
    turnovers = []

    for t, (w, r) in enumerate(zip(weights_seq, returns_seq, strict=False)):
        # Portfolio return for period t
        port_ret = (w * r).sum()
        portfolio_returns.append(port_ret)

        # Turnover
        if prev_weights_seq is not None and t < len(prev_weights_seq):
            prev_w = prev_weights_seq[t]
            # 确保维度对齐(可能不同股票集)
            turnover = torch.abs(w - prev_w).sum()
        elif t > 0:
            # 近似: 用上期权重漂移后的权重
            # 简化: 假设换手率 = sum(|w_new - 1/N|)
            n = len(w)
            equal_w = torch.ones_like(w) / n
            turnover = torch.abs(w - equal_w).sum()
        else:
            turnover = torch.tensor(0.0, device=w.device)

        turnovers.append(turnover)

    if not portfolio_returns:
        return torch.tensor(0.0, requires_grad=True)

    port_rets = torch.stack(portfolio_returns)
    mean_ret = port_rets.mean()
    std_ret = port_rets.std() + eps

    sharpe = mean_ret / std_ret

    mean_turnover = torch.stack(turnovers).mean() if turnovers else torch.tensor(0.0)

    loss = -sharpe + lambda_turnover * mean_turnover
    return loss


def compute_period_returns(
    weights: torch.Tensor,
    daily_returns: torch.Tensor,
) -> torch.Tensor:
    """计算一个持仓周期内的portfolio总收益。

    Args:
        weights: (N,) 初始权重
        daily_returns: (D, N) D天×N只股票的日收益率

    Returns:
        scalar: 周期总收益
    """
    # 累积: 每天更新权重(价格漂移)
    current_weights = weights.clone()
    cumulative = torch.tensor(0.0, device=weights.device)

    for d in range(daily_returns.shape[0]):
        # 当日portfolio收益
        day_ret = (current_weights * daily_returns[d]).sum()
        cumulative = cumulative + day_ret

        # 权重漂移(buy-and-hold)
        new_val = current_weights * (1 + daily_returns[d])
        total = new_val.sum()
        if total > 0:
            current_weights = new_val / total

    return cumulative


# ============================================================
# PortfolioTrainer: 训练循环
# ============================================================


@dataclass
class TrainerConfig:
    """训练配置。"""
    lr: float = 1e-3
    weight_decay: float = 0.01
    max_epochs: int = 500
    patience: int = 20
    max_grad_norm: float = 1.0
    lambda_turnover: float = 0.1
    cost_rate: float = 0.003
    max_weight: float = 0.10
    hidden: int = 64
    dropout: float = 0.3
    device: str = "cuda"
    print_every: int = 10


@dataclass
class TrainResult:
    """训练结果。"""
    best_epoch: int = 0
    best_val_sharpe: float = 0.0
    train_losses: list[float] = field(default_factory=list)
    val_sharpes: list[float] = field(default_factory=list)


class PortfolioTrainer:
    """层2 PortfolioMLP 训练器。

    每个WF fold独立训练:
    1. 加载Layer 1 LightGBM OOS得分(冻结)
    2. 加载因子特征
    3. 训练PortfolioMLP(loss=-Sharpe)
    4. 早停 + 梯度裁剪
    """

    def __init__(self, config: TrainerConfig):
        self.config = config
        self.device = torch.device(
            config.device if torch.cuda.is_available() else "cpu"
        )

    def train_fold(
        self,
        train_lgbm_scores: dict[str, np.ndarray],
        train_features: dict[str, np.ndarray],
        train_returns: dict[str, np.ndarray],
        valid_lgbm_scores: dict[str, np.ndarray],
        valid_features: dict[str, np.ndarray],
        valid_returns: dict[str, np.ndarray],
        n_features: int,
        rebal_dates_train: list[str],
        rebal_dates_valid: list[str],
    ) -> tuple[PortfolioMLP, TrainResult]:
        """训练单个fold的PortfolioMLP。

        Args:
            train_lgbm_scores: {rebal_date: (N,) scores}
            train_features: {rebal_date: (N, F) features}
            train_returns: {rebal_date: (N,) period returns}
            valid_*: 验证集同上
            n_features: 因子特征维度
            rebal_dates_train: 训练集调仓日列表(排序)
            rebal_dates_valid: 验证集调仓日列表(排序)

        Returns:
            (best_model, result)
        """
        cfg = self.config

        # 建模型
        model = PortfolioMLP(
            n_features=n_features,
            hidden=cfg.hidden,
            max_weight=cfg.max_weight,
            dropout=cfg.dropout,
        ).to(self.device)

        optimizer = torch.optim.Adam(
            model.parameters(),
            lr=cfg.lr,
            weight_decay=cfg.weight_decay,
        )

        # 训练数据→tensor
        train_data = self._prepare_data(
            train_lgbm_scores, train_features, train_returns, rebal_dates_train
        )
        valid_data = self._prepare_data(
            valid_lgbm_scores, valid_features, valid_returns, rebal_dates_valid
        )

        result = TrainResult()
        best_state = None
        best_val_sharpe = -float("inf")
        patience_counter = 0

        for epoch in range(cfg.max_epochs):
            # ── Train ──
            model.train()
            optimizer.zero_grad()

            weights_seq = []
            returns_seq = []

            for scores_t, features_t, returns_t in train_data:
                w = model(scores_t, features_t)
                weights_seq.append(w)
                returns_seq.append(returns_t)

            loss = sharpe_loss(
                weights_seq, returns_seq,
                lambda_turnover=cfg.lambda_turnover,
                cost_rate=cfg.cost_rate,
            )

            loss.backward()
            clip_grad_norm_(model.parameters(), cfg.max_grad_norm)
            optimizer.step()

            result.train_losses.append(loss.item())

            # ── Validate ──
            if epoch % cfg.print_every == 0 or epoch == cfg.max_epochs - 1:
                model.eval()
                with torch.no_grad():
                    val_rets = []
                    for scores_t, features_t, returns_t in valid_data:
                        w = model(scores_t, features_t)
                        port_ret = (w * returns_t).sum()
                        val_rets.append(port_ret.item())

                if val_rets:
                    val_mean = np.mean(val_rets)
                    val_std = np.std(val_rets) + 1e-8
                    val_sharpe = val_mean / val_std
                else:
                    val_sharpe = 0.0

                result.val_sharpes.append(val_sharpe)

                if epoch % cfg.print_every == 0:
                    print(f"    Epoch {epoch:>4d}: loss={loss.item():.4f}, "
                          f"val_sharpe={val_sharpe:.4f}")

                # Early stopping
                if val_sharpe > best_val_sharpe:
                    best_val_sharpe = val_sharpe
                    best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                    patience_counter = 0
                    result.best_epoch = epoch
                    result.best_val_sharpe = val_sharpe
                else:
                    patience_counter += 1
                    if patience_counter >= cfg.patience:
                        print(f"    Early stopping at epoch {epoch} "
                              f"(best val_sharpe={best_val_sharpe:.4f} at epoch {result.best_epoch})")
                        break

        # 恢复最优模型
        if best_state is not None:
            model.load_state_dict(best_state)
        model.to(self.device)

        return model, result

    def predict(
        self,
        model: PortfolioMLP,
        lgbm_scores: np.ndarray,
        features: np.ndarray,
        codes: list[str],
    ) -> dict[str, float]:
        """用训练好的模型预测portfolio权重。

        Args:
            model: 训练好的PortfolioMLP
            lgbm_scores: (N,) 预测得分
            features: (N, F) 因子特征
            codes: 股票代码列表

        Returns:
            {code: weight}
        """
        model.eval()
        with torch.no_grad():
            scores_t = torch.tensor(lgbm_scores, dtype=torch.float32).to(self.device)
            feat_t = torch.tensor(features, dtype=torch.float32).to(self.device)
            weights = model(scores_t, feat_t).cpu().numpy()

        # 过滤零权重
        result = {}
        for code, w in zip(codes, weights, strict=True):
            if w > 0.001:
                result[code] = float(w)

        # 重归一化
        total = sum(result.values())
        if total > 0:
            result = {k: v / total for k, v in result.items()}

        return result

    def _prepare_data(
        self,
        lgbm_scores: dict[str, np.ndarray],
        features: dict[str, np.ndarray],
        returns: dict[str, np.ndarray],
        rebal_dates: list[str],
    ) -> list[tuple[torch.Tensor, torch.Tensor, torch.Tensor]]:
        """将numpy数据转为GPU tensor列表。"""
        data = []
        for rd in rebal_dates:
            if rd not in lgbm_scores or rd not in features or rd not in returns:
                continue
            s = torch.tensor(lgbm_scores[rd], dtype=torch.float32).to(self.device)
            f = torch.tensor(features[rd], dtype=torch.float32).to(self.device)
            r = torch.tensor(returns[rd], dtype=torch.float32).to(self.device)
            data.append((s, f, r))
        return data
