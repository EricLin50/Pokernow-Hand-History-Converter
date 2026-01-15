import json
import sys
from datetime import datetime, timezone

def hand_id_to_number(hand_id):
    """Convert alphanumeric hand ID to numeric-only identifier."""
    # Use hash to convert string to integer, then make it positive
    hash_value = abs(hash(hand_id))
    # Convert to string to ensure it's numeric-only
    return str(hash_value)

def fmt_money(cents):
    return f"${cents/100:.2f}"

def fmt_time(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y/%m/%d %H:%M:%S ET")

def seat_map(players):
    return {p["seat"]: p for p in players}

def write_hand(hand, out, hero, game_id):
    sb = hand["smallBlind"]
    bb = hand["bigBlind"]
    hand_id = hand["id"]
    hand_number = hand_id_to_number(hand_id)
    started = fmt_time(hand["startedAt"])

    out.write(
        f"PokerStarsCollection Hand #{hand_number}:  Hold'em No Limit "
        f"({fmt_money(sb)}/{fmt_money(bb)} USD) - {started}\n"
    )

    # Create seat mapping and renumber sequentially
    original_players = seat_map(hand["players"])
    sorted_seats = sorted(original_players.keys())
    seat_renumber = {old_seat: new_seat for new_seat, old_seat in enumerate(sorted_seats, 1)}
    players = {seat_renumber[old_seat]: original_players[old_seat] for old_seat in sorted_seats}
    
    # Renumber dealer seat
    dealer_seat_original = hand['dealerSeat']
    dealer_seat = seat_renumber.get(dealer_seat_original, dealer_seat_original)

    out.write(
        f"Table 'PokerNow {game_id}' "
        f"9-max Seat #{dealer_seat} is the button\n"
    )

    # Write seats with renumbered positions
    for seat in sorted(players.keys()):
        p = players[seat]
        out.write(
            f"Seat {seat}: {p['name']} "
            f"({fmt_money(p['stack'])} in chips) \n"
        )

    # Track blinds, actions, and results for summary
    player_actions = {}
    player_shown_cards = {}
    player_hand_descriptions = {}
    player_fold_stage = {}
    player_bet_stage = {}
    player_winnings = {}  # Track winnings by renumbered seat
    sb_seat = None
    bb_seat = None
    total_pot = 0
    total_winnings = 0
    last_bet_amount = 0
    street_bet = 0  # Will be set by big blind

    for seat in sorted(players.keys()):
        player_actions[seat] = []
        player_fold_stage[seat] = None
        player_bet_stage[seat] = False

    # Process events to find blinds first (before HOLE CARDS)
    blinds_posted = []
    other_events = []
    
    for e in hand["events"]:
        pl = e["payload"]
        t = pl["type"]
        if t in (2, 3):  # blinds
            blinds_posted.append(e)
        else:
            other_events.append(e)

    # Write blinds before HOLE CARDS
    for e in blinds_posted:
        pl = e["payload"]
        t = pl["type"]
        seat_orig = pl.get("seat")
        seat = seat_renumber.get(seat_orig, seat_orig)
        player = players.get(seat) if seat else None
        
        if player:
                out.write(
                    f"{player['name']}: "
                    f"{'posts big blind' if t == 2 else 'posts small blind'} "
                    f"{fmt_money(pl['value'])} \n"
                )
                if t == 2:  # Big blind
                    bb_seat = seat
                    last_bet_amount = pl['value']
                    street_bet = pl['value']  # Initialize street bet
                else:  # Small blind
                    sb_seat = seat
                player_actions[seat].append("blind")

    out.write("*** HOLE CARDS ***\n")

    # Hero hole cards only
    for p in players.values():
        if p["name"] == hero and "hand" in p and p["hand"]:
            valid_cards = [c for c in p["hand"] if c]
            if len(valid_cards) == 2:
                cards = " ".join(valid_cards)
                out.write(f"Dealt to {hero} [{cards}]\n")

    board = []
    # street_bet is already initialized from big blind processing above
    current_street = "preflop"
    active_players = set(players.keys())  # Track who's still in the hand
    uncalled_bet_seat = None
    uncalled_bet_amount = 0
    bet_was_called = False  # Track if the last bet was called

    # Process other events
    for event_idx, e in enumerate(other_events):
        pl = e["payload"]
        t = pl["type"]
        seat_orig = pl.get("seat")
        seat = seat_renumber.get(seat_orig, seat_orig) if seat_orig else None
        player = players.get(seat) if seat else None

        if t == 9:  # board cards
            cards = [c for c in pl.get("cards", []) if c]
            if not cards:
                continue
            if pl["turn"] == 1:
                board = cards
                out.write(f"*** FLOP *** [{' '.join(board)}]\n")
                street_bet = 0
                current_street = "flop"
            elif pl["turn"] == 2:
                board += cards
                out.write(
                    f"*** TURN *** [{' '.join(board[:-1])}] [{board[-1]}]\n"
                )
                street_bet = 0
                current_street = "turn"
            elif pl["turn"] == 3:
                board += cards
                out.write(
                    f"*** RIVER *** [{' '.join(board[:-1])}] [{board[-1]}]\n"
                )
                street_bet = 0
                current_street = "river"

        elif t == 7:  # call
            if player:
                out.write(f"{player['name']}: calls {fmt_money(pl['value'])} \n")
                player_actions[seat].append("call")
                # If this call matches the last bet, mark it as called
                if uncalled_bet_seat and pl['value'] >= last_bet_amount:
                    bet_was_called = True
                    uncalled_bet_seat = None
                    uncalled_bet_amount = 0

        elif t == 8:  # bet / raise
            if player:
                bet_amount = pl['value']
                player_bet_stage[seat] = True
                if bet_amount > street_bet:
                    if street_bet > 0:
                        raise_amount = bet_amount - street_bet
                        out.write(f"{player['name']}: raises {fmt_money(raise_amount)} to {fmt_money(bet_amount)} \n")
                        player_actions[seat].append("raise")
                    else:
                        out.write(f"{player['name']}: bets {fmt_money(bet_amount)} \n")
                        player_actions[seat].append("bet")
                    street_bet = bet_amount
                    last_bet_amount = bet_amount
                    # Mark this as a potential uncalled bet (will be cleared if called)
                    uncalled_bet_seat = seat
                    uncalled_bet_amount = bet_amount
                    bet_was_called = False
                else:
                    out.write(f"{player['name']}: bets {fmt_money(bet_amount)} \n")
                    player_actions[seat].append("bet")
                    street_bet = bet_amount
                    last_bet_amount = bet_amount
                    uncalled_bet_seat = seat
                    uncalled_bet_amount = bet_amount
                    bet_was_called = False

        elif t == 0:  # check
            if player:
                out.write(f"{player['name']}: checks \n")
                player_actions[seat].append("check")

        elif t == 11:  # fold
            if player:
                out.write(f"{player['name']}: folds \n")
                player_actions[seat].append("fold")
                player_fold_stage[seat] = current_street
                active_players.discard(seat)
                # If there's an uncalled bet and this was the last player who could call, bet remains uncalled
                # (Will be handled before SHOW DOWN or win pot)

        elif t == 15:  # showdown
            # Check for uncalled bet before SHOW DOWN (if hand ended on flop or turn)
            if uncalled_bet_seat and uncalled_bet_seat in active_players:
                if current_street in ["flop", "turn"]:
                    # Check if bettor is the only active player (meaning bet wasn't called)
                    other_active = active_players - {uncalled_bet_seat}
                    if not other_active or not bet_was_called:
                        bettor_player = players[uncalled_bet_seat]
                        out.write(f"Uncalled bet ({fmt_money(uncalled_bet_amount)}) returned to {bettor_player['name']}\n")
                        uncalled_bet_seat = None
                        uncalled_bet_amount = 0
            # Only write showdown header if cards are actually shown
            remaining_show_card_events = [ev for ev in other_events[event_idx+1:] if ev["payload"].get("type") == 12]
            if len(player_shown_cards) > 0 or len(remaining_show_card_events) > 0:
                out.write("*** SHOW DOWN ***\n")

        elif t == 12:  # show cards
            if player and pl.get("cards"):
                valid_cards = [c for c in pl["cards"] if c]
                if valid_cards:
                    cards = " ".join(valid_cards)
                    hand_desc = pl.get("handDescription", "")
                    if hand_desc:
                        out.write(f"{player['name']}: shows [{cards}] ({hand_desc})\n")
                    else:
                        out.write(f"{player['name']}: shows [{cards}]\n")
                    player_shown_cards[seat] = cards
                    player_hand_descriptions[seat] = hand_desc

        elif t == 10:  # win pot
            # Check for uncalled bet before win pot (if hand ended on flop or turn without showdown)
            if uncalled_bet_seat and uncalled_bet_seat in active_players:
                if current_street in ["flop", "turn"]:
                    # Check if bettor is the only active player (meaning bet wasn't called)
                    other_active = active_players - {uncalled_bet_seat}
                    if not other_active or not bet_was_called:
                        bettor_player = players[uncalled_bet_seat]
                        out.write(f"Uncalled bet ({fmt_money(uncalled_bet_amount)}) returned to {bettor_player['name']}\n")
                        uncalled_bet_seat = None
                        uncalled_bet_amount = 0
            if player:
                pot_amount = pl['value']
                total_pot = pl.get('pot', pot_amount)
                total_winnings += pot_amount
                player_winnings[seat] = pot_amount
                out.write(
                    f"{player['name']} collected "
                    f"{fmt_money(pot_amount)} from pot\n"
                )
                if seat not in player_shown_cards:
                    out.write(f"{player['name']}: doesn't show hand \n")

    # Calculate rake
    rake = total_pot - total_winnings if total_pot > 0 else 0

    # Write SUMMARY section
    out.write("*** SUMMARY ***\n")
    out.write(f"Total pot ${total_pot/100:.2f} | Rake ${rake/100:.2f} \n")
    if board:
        out.write(f"Board [{' '.join(board)}]\n")

    # Write seat summaries
    for seat in sorted(players.keys()):
        p = players[seat]
        seat_info = f"Seat {seat}: {p['name']}"

        # Add position info
        if seat == dealer_seat:
            seat_info += " (button)"
        if seat == sb_seat:
            seat_info += " (small blind)"
        if seat == bb_seat:
            seat_info += " (big blind)"

        # Add action/result
        if seat in player_shown_cards:
            won_amount = player_winnings.get(seat)
            cards = player_shown_cards[seat]
            hand_desc = player_hand_descriptions.get(seat, "")
            if won_amount:
                if hand_desc:
                    seat_info += f" showed [{cards}] and won (${won_amount/100:.2f}) with {hand_desc}"
                else:
                    seat_info += f" showed [{cards}] and won (${won_amount/100:.2f})"
            else:
                if hand_desc:
                    seat_info += f" showed [{cards}] and lost with {hand_desc}"
                else:
                    seat_info += f" showed [{cards}] and lost"
        elif player_fold_stage[seat] is not None:
            stage = player_fold_stage[seat]
            if stage == "preflop":
                if not player_bet_stage[seat]:
                    seat_info += " folded before Flop (didn't bet)"
                else:
                    seat_info += " folded before Flop"
            elif stage == "flop":
                seat_info += " folded on the Flop"
            elif stage == "turn":
                seat_info += " folded on the Turn"
            elif stage == "river":
                seat_info += " folded on the River"
        else:
            # Player collected pot without showing
            won_amount = player_winnings.get(seat)
            if won_amount:
                seat_info += f" collected (${won_amount/100:.2f})"

        out.write(seat_info + "\n")

    out.write("\n\n\n")

def main():
    if len(sys.argv) != 4:
        print(
            "Usage: python pokernow_to_pokerstars.py "
            "input.json output.txt \"Hero Name\""
        )
        sys.exit(1)

    input_file, output_file, hero = sys.argv[1:]

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    game_id = data.get("gameId", "Unknown")

    with open(output_file, "w", encoding="utf-8") as out:
        for hand in data["hands"]:
            write_hand(hand, out, hero, game_id)

    print("Conversion complete.")

if __name__ == "__main__":
    main()
