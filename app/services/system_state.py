from datetime import date

from sqlalchemy import delete, func, select

from app.core.config import Settings
from app.db.models import AccountSnapshot, PaperPosition
from app.db.session import SessionLocal, init_db
from app.schemas.system import AccountState


class SystemStateService:
    def __init__(self, settings: Settings) -> None:
        self._trading_enabled = settings.trading_enabled
        self._initial_equity = 1000.0
        init_db()

    def get_account_state(self) -> AccountState:
        with SessionLocal() as db:
            snapshot = db.scalars(
                select(AccountSnapshot).order_by(AccountSnapshot.timestamp.desc()).limit(1)
            ).first()
            if snapshot is None:
                snapshot = self._create_initial_snapshot(db)
            return self._to_schema(snapshot)

    def set_trading_enabled(self, enabled: bool) -> AccountState:
        with SessionLocal() as db:
            current = self._latest_or_initial(db)
            snapshot = AccountSnapshot(
                equity=current.equity,
                realized_pnl=current.realized_pnl,
                daily_loss=current.daily_loss,
                weekly_loss=current.weekly_loss,
                peak_equity=current.peak_equity,
                drawdown=current.drawdown,
                trades_today=current.trades_today,
                open_positions=current.open_positions,
                trading_enabled=enabled,
            )
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)
            return self._to_schema(snapshot)

    def register_paper_trade(self) -> AccountState:
        with SessionLocal() as db:
            current = self._latest_or_initial(db)
            open_positions = db.scalar(
                select(func.count(PaperPosition.id)).where(PaperPosition.status == "OPEN")
            )
            snapshot = AccountSnapshot(
                equity=current.equity,
                realized_pnl=current.realized_pnl,
                daily_loss=current.daily_loss,
                weekly_loss=current.weekly_loss,
                peak_equity=current.peak_equity,
                drawdown=current.drawdown,
                trades_today=self._count_trades_today(db),
                open_positions=open_positions or 0,
                trading_enabled=current.trading_enabled,
            )
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)
            return self._to_schema(snapshot)

    def register_closed_position(self, realized_pnl: float) -> AccountState:
        with SessionLocal() as db:
            current = self._latest_or_initial(db)
            equity = current.equity + realized_pnl
            peak_equity = max(current.peak_equity, equity)
            drawdown = max(0.0, peak_equity - equity)
            daily_loss = self._sum_losses_today(db, realized_pnl)
            weekly_loss = self._sum_losses_this_week(db, realized_pnl)
            open_positions = db.scalar(
                select(func.count(PaperPosition.id)).where(PaperPosition.status == "OPEN")
            )
            snapshot = AccountSnapshot(
                equity=equity,
                realized_pnl=current.realized_pnl + realized_pnl,
                daily_loss=daily_loss,
                weekly_loss=weekly_loss,
                peak_equity=peak_equity,
                drawdown=drawdown,
                trades_today=self._count_trades_today(db),
                open_positions=open_positions or 0,
                trading_enabled=current.trading_enabled,
            )
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)
            return self._to_schema(snapshot)

    def reset_simulation(self) -> AccountState:
        with SessionLocal() as db:
            db.execute(delete(PaperPosition))
            snapshot = AccountSnapshot(
                equity=self._initial_equity,
                realized_pnl=0,
                daily_loss=0,
                weekly_loss=0,
                peak_equity=self._initial_equity,
                drawdown=0,
                trades_today=0,
                open_positions=0,
                trading_enabled=True,
            )
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)
            return self._to_schema(snapshot)

    def _latest_or_initial(self, db) -> AccountSnapshot:
        snapshot = db.scalars(
            select(AccountSnapshot).order_by(AccountSnapshot.timestamp.desc()).limit(1)
        ).first()
        return snapshot or self._create_initial_snapshot(db)

    def _create_initial_snapshot(self, db) -> AccountSnapshot:
        snapshot = AccountSnapshot(
            equity=self._initial_equity,
            realized_pnl=0,
            daily_loss=0,
            weekly_loss=0,
            peak_equity=self._initial_equity,
            drawdown=0,
            trades_today=0,
            open_positions=0,
            trading_enabled=self._trading_enabled,
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        return snapshot

    @staticmethod
    def _to_schema(snapshot: AccountSnapshot) -> AccountState:
        return AccountState(
            equity=snapshot.equity,
            realized_pnl=snapshot.realized_pnl,
            daily_loss=snapshot.daily_loss,
            weekly_loss=snapshot.weekly_loss,
            peak_equity=snapshot.peak_equity,
            drawdown=snapshot.drawdown,
            trades_today=snapshot.trades_today,
            open_positions=snapshot.open_positions,
            trading_enabled=snapshot.trading_enabled,
        )

    @staticmethod
    def _count_trades_today(db) -> int:
        today = date.today()
        return db.scalar(
            select(func.count(PaperPosition.id)).where(func.date(PaperPosition.opened_at) == str(today))
        ) or 0

    @staticmethod
    def _sum_losses_today(db, pending_pnl: float = 0) -> float:
        today = date.today()
        losses = db.scalars(
            select(PaperPosition.realized_pnl).where(
                PaperPosition.status == "CLOSED",
                func.date(PaperPosition.closed_at) == str(today),
                PaperPosition.realized_pnl < 0,
            )
        ).all()
        total = sum(abs(value or 0) for value in losses)
        return total + abs(pending_pnl if pending_pnl < 0 else 0)

    @staticmethod
    def _sum_losses_this_week(db, pending_pnl: float = 0) -> float:
        today = date.today()
        week_start = today.fromordinal(today.toordinal() - today.weekday())
        losses = db.scalars(
            select(PaperPosition.realized_pnl).where(
                PaperPosition.status == "CLOSED",
                func.date(PaperPosition.closed_at) >= str(week_start),
                PaperPosition.realized_pnl < 0,
            )
        ).all()
        total = sum(abs(value or 0) for value in losses)
        return total + abs(pending_pnl if pending_pnl < 0 else 0)
