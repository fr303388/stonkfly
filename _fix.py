p = 'stonkfly/cli.py'
s = open(p, 'r', encoding='utf-8').read()

# 1. Add learning influence before the want_buy/want_sell logic
old = """                # 果蠅參考纏論建議再下單：不能自己無腦下單
                # 買入：雙方共識 或 纏論主導(果蠅不反對)
                want_buy = (fly_natural_side == "BUY" and chan_sig == "BUY") or (chan_sig == "BUY" and fly_natural_side == "HOLD")
                # 賣出：雙方共識 或 纏論主導(果蠅不反對)
                want_sell = (fly_natural_side == "SELL" and chan_sig == "SELL") or (chan_sig == "SELL" and fly_natural_side == "HOLD")"""

new = """                # === 學習成果接入交易決策 ===
                # 纏論理論學習偏見：掌握度越高，對纏論訊號信任度越高
                _learn_bias = chan_learner.get_trading_bias()
                _buy_conf = _learn_bias.get("buy_confidence", 0)
                _sell_conf = _learn_bias.get("sell_confidence", 0)
                _overall_knowledge = _learn_bias.get("overall", 0)
                # 實戰學習器評估目前市場狀態
                _practical_signal = practical_learner.evaluate_signal(
                    czsc_obs, has_position, current_price, avg_entry_price
                ) if hasattr(practical_learner, 'evaluate_signal') else {"signal": "HOLD", "confidence": 0, "reason": ""}
                _prac_sig = _practical_signal.get("signal", "HOLD")
                _prac_conf = _practical_signal.get("confidence", 0)
                _prac_reason = _practical_signal.get("reason", "")

                # 果蠅參考纏論建議再下單：不能自己無腦下單
                # 基礎買入：雙方共識 或 纏論主導(果蠅不反對)
                want_buy = (fly_natural_side == "BUY" and chan_sig == "BUY") or (chan_sig == "BUY" and fly_natural_side == "HOLD")
                # 基礎賣出：雙方共識 或 纏論主導(果蠅不反對)
                want_sell = (fly_natural_side == "SELL" and chan_sig == "SELL") or (chan_sig == "SELL" and fly_natural_side == "HOLD")

                # 學習加成：實戰學習器高信心買入(>60)且果蠅不反對 → 也可買入
                if _prac_sig == "BUY" and _prac_conf > 60 and fly_natural_side != "SELL" and not has_position:
                    want_buy = True
                # 學習加成：實戰學習器高信心賣出(>60)且果蠅不反對 → 也可賣出
                if _prac_sig == "SELL" and _prac_conf > 60 and fly_natural_side != "BUY" and has_position:
                    want_sell = True
                # 知識不足時(<30)更保守：需要果蠅+纏論共識才買
                if _overall_knowledge < 30 and not (fly_natural_side == "BUY" and chan_sig == "BUY"):
                    want_buy = False"""

s = s.replace(old, new, 1)

# 2. Add learning context to buy decision note
old_buy = """                    if fly_natural_side == "BUY" and chan_sig == "BUY":
                        chan_imitation_correct += 1
                        decision_tag = "[果蠅+纏論共識]"
                        decision_reason = f"果蠅參考纏論指標({chan_summary})後同意買入，閘門{fly_gate} 左右腦差{fly_diff:.1f}Hz，雙方共識入場，等待纏論賣出訊號"
                    else:
                        decision_tag = "[纏論主導買入]"
                        decision_reason = f"纏論指標觸發買入:{chan_summary} 信心{chan_conf:.0f}%，果蠅不反對({fly_natural_side})，跟隨入場，等待纏論賣出訊號\""""

new_buy = """                    if _prac_sig == "BUY" and _prac_conf > 60 and chan_sig != "BUY":
                        decision_tag = "[實戰學習主導買入]"
                        decision_reason = f"實戰學習器高信心({_prac_conf:.0f}%)觸發:{_prac_reason}，理論知識{_overall_knowledge:.0f}%，果蠅{fly_natural_side}不反對，跟隨入場"
                    elif fly_natural_side == "BUY" and chan_sig == "BUY":
                        chan_imitation_correct += 1
                        decision_tag = "[果蠅+纏論共識]"
                        decision_reason = f"果蠅參考纏論指標({chan_summary})後同意買入，閘門{fly_gate} 左右腦差{fly_diff:.1f}Hz，理論知識{_overall_knowledge:.0f}% 買入信心{_buy_conf:.0f}%，雙方共識入場"
                    else:
                        decision_tag = "[纏論主導買入]"
                        decision_reason = f"纏論指標觸發買入:{chan_summary} 信心{chan_conf:.0f}%，果蠅不反對({fly_natural_side})，理論知識{_overall_knowledge:.0f}% 買入信心{_buy_conf:.0f}%，跟隨入場\""""

s = s.replace(old_buy, new_buy, 1)

# 3. Add learning context to sell decision note
old_sell = """                    if fly_natural_side == "SELL":
                        decision_tag = "[果蠅+纏論共識賣出]"
                        decision_reason = f"果蠅與纏論同時指示賣出，{chan_summary}，全數出清，盈虧{_pnl_pct:+.3f}%"
                    else:
                        decision_tag = "[纏論主導賣出]"
                        decision_reason = f"纏論指標觸發賣出:{chan_summary} 信心{chan_conf:.0f}%，果蠅建議{fly_natural_side}，跟隨纏論全數出清，盈虧{_pnl_pct:+.3f}%\""""

new_sell = """                    if _prac_sig == "SELL" and _prac_conf > 60 and chan_sig != "SELL":
                        decision_tag = "[實戰學習主導賣出]"
                        decision_reason = f"實戰學習器高信心({_prac_conf:.0f}%)觸發:{_prac_reason}，賣出信心{_sell_conf:.0f}%，全數出清，盈虧{_pnl_pct:+.3f}%"
                    elif fly_natural_side == "SELL":
                        decision_tag = "[果蠅+纏論共識賣出]"
                        decision_reason = f"果蠅與纏論同時指示賣出，{chan_summary}，賣出信心{_sell_conf:.0f}%，全數出清，盈虧{_pnl_pct:+.3f}%"
                    else:
                        decision_tag = "[纏論主導賣出]"
                        decision_reason = f"纏論指標觸發賣出:{chan_summary} 信心{chan_conf:.0f}%，果蠅建議{fly_natural_side}，賣出信心{_sell_conf:.0f}%，跟隨纏論全數出清，盈虧{_pnl_pct:+.3f}%\""""

s = s.replace(old_sell, new_sell, 1)

# 4. Add learning info to HOLD observation note
old_hold = """                    neural["decision_note"] = f"[持有中] 均價${avg_entry_price:.2f} 現價${current_price:.2f} ({_current_pct:+.3f}%) | 等待纏論賣出訊號 | 果蠅:{fly_natural_side} 纏論:{chan_sig}\""""

new_hold = """                    _learn_note = f" 知識{_overall_knowledge:.0f}% 實戰:{_prac_sig}({_prac_conf:.0f}%)" if _prac_sig != "HOLD" else f" 知識{_overall_knowledge:.0f}%"
                    neural["decision_note"] = f"[持有中] 均價${avg_entry_price:.2f} 現價${current_price:.2f} ({_current_pct:+.3f}%) | 等待賣出訊號 | 果蠅:{fly_natural_side} 纏論:{chan_sig}{_learn_note}\""""

s = s.replace(old_hold, new_hold, 1)

# 5. Add learning info to no-position observation
old_obs = """                    neural["decision_note"] = f"[觀察] 果蠅:{fly_natural_side} 纏論:{chan_sig} (模仿率{imitation_rate:.0f}%) 最後更新{_last_obs_time}\""""

new_obs = """                    _learn_note2 = f" 知識{_overall_knowledge:.0f}% 實戰:{_prac_sig}" if _prac_sig != "HOLD" else f" 知識{_overall_knowledge:.0f}%"
                    neural["decision_note"] = f"[觀察] 果蠅:{fly_natural_side} 纏論:{chan_sig} (模仿率{imitation_rate:.0f}%){_learn_note2} 最後更新{_last_obs_time}\""""

s = s.replace(old_obs, new_obs, 1)

open(p, 'w', encoding='utf-8').write(s)
print('learning connected to trading')
