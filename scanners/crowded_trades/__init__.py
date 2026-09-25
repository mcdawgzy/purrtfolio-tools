"""Crowded Trades Scanner — cross-signal crowding analysis.

Aggregates sentiment signals from the existing scanner ecosystem (short
interest, put/call ratios, unusual options activity, IV rank, price
momentum, correlation matrices) into a per-ticker *crowdedness* score.

A "crowded trade" is one where many market participants are positioned
on the same side — the risk being a cascade if the consensus breaks.
"""
