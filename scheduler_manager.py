from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple, Optional
from fsrs import Scheduler, Card as FSRSCard, Rating, State
from models import ReviewObject

class SchedulerManager:
    """Manages FSRS scheduling calculations and state updates."""

    def __init__(self):
        self.scheduler = Scheduler()

    def get_interval_forecasts(self, review_obj: ReviewObject) -> Dict[Rating, str]:
        """
        Calculate and format the next review interval for each rating option
        without mutating the current card state.
        """
        now = datetime.now(timezone.utc)
        forecasts = {}
        for rating in [Rating.Again, Rating.Hard, Rating.Good, Rating.Easy]:
            # Simulate review
            simulated_card, _ = self.scheduler.review_card(review_obj.fsrs_card, rating, now)
            if simulated_card.due and simulated_card.last_review:
                delta = simulated_card.due - simulated_card.last_review
            elif simulated_card.due:
                delta = simulated_card.due - now
            else:
                delta = timedelta(minutes=10)
            forecasts[rating] = self.format_timedelta(delta)
        return forecasts

    def get_card_retrievability(self, review_obj: ReviewObject, now: Optional[datetime] = None) -> float:
        """
        Calculate single card retrievability R(t) in [0.0, 1.0].
        If card is New (never reviewed), returns 0.0.
        """
        now_dt = now or datetime.now(timezone.utc)
        if review_obj.fsrs_card.last_review is None:
            return 0.0
        try:
            ret = self.scheduler.get_card_retrievability(review_obj.fsrs_card, now_dt)
            return max(0.0, min(1.0, float(ret))) if ret is not None else 0.0
        except Exception:
            return 0.0


    def get_note_retention(self, cards: list, now: Optional[datetime] = None) -> float:
        """
        Calculate joint retention P(∩ A_i) = ∏ R_i(t) for a sequence of cards.
        """
        if not cards:
            return 1.0
        now_dt = now or datetime.now(timezone.utc)
        product = 1.0
        for card in cards:
            r_i = self.get_card_retrievability(card, now_dt)
            product *= r_i
        return product

    def rate_object(self, review_obj: ReviewObject, rating: Rating) -> FSRSCard:
        """Rate a card and update its FSRS state permanently."""
        now = datetime.now(timezone.utc)
        updated_card, _ = self.scheduler.review_card(review_obj.fsrs_card, rating, now)
        review_obj.fsrs_card = updated_card
        return updated_card

    @staticmethod
    def format_timedelta(td: timedelta) -> str:
        """Format timedelta into human readable short strings like '10m', '1.2h', '3.5d'."""
        seconds = max(1, int(td.total_seconds()))
        if seconds < 3600:
            minutes = max(1, seconds // 60)
            return f"{minutes}m"
        elif seconds < 86400:
            hours = seconds / 3600.0
            return f"{hours:.1f}h"
        else:
            days = seconds / 86400.0
            return f"{days:.1f}d"

    def reschedule_card(self, review_obj: ReviewObject, logs: list) -> int:
        """
        Replay a single card's historical review logs in chronological order
        to recalculate its exact current FSRS state (stability, difficulty, due, state).
        Returns number of replayed logs.
        """
        card_logs = sorted([l for l in logs if l.card_id == review_obj.item_id], key=lambda x: x.review_time)
        f_card = FSRSCard()
        for rlog in card_logs:
            try:
                dt = datetime.fromisoformat(rlog.review_time)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                rating = Rating(rlog.rating)
                f_card, _ = self.scheduler.review_card(f_card, rating, dt)
            except Exception as e:
                print(f"Error replaying review log for card {review_obj.item_id}: {e}")
        review_obj.fsrs_card = f_card
        return len(card_logs)

    def reschedule_note(self, note, logs: list) -> Tuple[int, int]:
        """
        Replay historical review logs for all cards inside a note.
        Returns (recalculated_cards_count, total_logs_replayed).
        """
        total_logs = 0
        card_count = 0
        for card in note.cards:
            n_logs = self.reschedule_card(card, logs)
            total_logs += n_logs
            card_count += 1
        return card_count, total_logs

    def reschedule_course(self, course, logs: list) -> Tuple[int, int]:
        """
        Replay historical review logs for all cards inside an entire course.
        Returns (recalculated_cards_count, total_logs_replayed).
        """
        total_logs = 0
        card_count = 0
        for note in course.notes:
            c_cnt, l_cnt = self.reschedule_note(note, logs)
            card_count += c_cnt
            total_logs += l_cnt
        return card_count, total_logs


