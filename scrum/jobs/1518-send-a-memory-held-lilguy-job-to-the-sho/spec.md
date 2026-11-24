Send a memory-held lilguy job to the shop sooner
Lane: fast

Send a memory-held lilguy job to the shop sooner (Trevor asked 11 times about stalls and overload; Time sinks 2 jobs, about 3h20m, 019-services-page-spray-tan-changes-from-sta waited 2h59m for a 3m shop run): in `skills/trevskills-scrum/board.py` shop_excluded, add SHOP_LILGUY_MEM_HELD_SECS = 1800 so a lilguy job whose queue-gates.txt names swap or vm_pressure may go to the shop after 30 min (other gates keep SHOP_LILGUY_HELD_SECS 7200), and count the hold from the job's current-gates.json held seconds (job 1485) instead of play_queued or updatedAt, which later board writes push forward; update the Pool line in `skills/trevskills-scrum/lanes/shop.md` and add cases in `tests/test_board_runs_on.py` next to the 7200 pin. Lane: fast.
Hard stops: none
