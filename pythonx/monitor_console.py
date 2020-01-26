"""
Feature to get a buffer with jupyter output
"""

# Standard
from time import sleep
import vim

# Local
from message_parser import parse_messages, prettify_execute_intput, \
    unquote_string, str_to_vim, echom

try:
    from queue import Empty
except ImportError:
    from Queue import Empty


class Monitor:
    """Jupyter kernel monitor buffer and message line"""
    def __init__(self, section_info):
        self.si = section_info
        self.cmd = None
        self.cmd_id = None
        self.cmd_count = 0

    def set_cmd_count(self, num):
        """Set command count number, to record it if wanted (console buffer)"""
        self.cmd_count = num

    def monitorable(self, fct):
        """Decorator to monitor messages"""
        def wrapper(*args, **kwargs):
            # Check in
            if not self.si.client.check_connection_or_warn(): return

            # Call
            fct(*args, **kwargs)

            # Clause
            self.si.vim.set_monitor_bools()
            if not self.si.vim.verbose and not self.si.vim.monitor_console: return

            # Launch update threads
            self.update_msgs()
        return wrapper

    def update_msgs(self):
        """Launch pending messages grabbers (Sync but not for long)
        Param: console (boolean): should I update console
            prompt  (boolean): should I update prompt
            last_cmd (string): not used already

        """
        # Open the Jupyter terminal in vim, and move cursor to it
        b_nb = vim.eval('jupyter_monitor_console#OpenJupyterTerm()')
        if -1 == b_nb:
            echom('__jupyter_term__ failed to open!', 'Error')
            return

        # Define time: thread (additive) sleep and timer wait
        timer_intervals = self.si.vim.get_timer_intervals()
        thread_intervals = [50]
        for i in range(len(timer_intervals)-1):
            thread_intervals.append(timer_intervals[i+1] - timer_intervals[i] - 50)

        # Create thread
        self.si.sync.start_thread(
            target=self.thread_fetch_msgs,
            args=[thread_intervals])

        # Launch timers
        for sleep_ms in timer_intervals:
            vim_cmd = ('call timer_start(' + str(sleep_ms) +
                       ', "jupyter_monitor_console#UpdateConsoleBuffer")')
            vim.command(vim_cmd)

    def thread_fetch_msgs(self, intervals):
        """Update message that timer will append to console message
        """
        io_cache = []
        for sleep_ms in intervals:
            # Sleep ms
            if self.si.sync.check_stop(): return
            sleep(sleep_ms / 1000)
            if self.si.sync.check_stop(): return

            # Get messages
            msgs = self.si.client.get_pending_msgs()
            io_new = parse_messages(self.si, msgs)

            # Insert code line Check not already here (check with substr 'Py [')
            do_add_cmd = self.cmd is not None
            do_add_cmd &= len(io_new) != 0
            do_add_cmd &= not any(self.si.lang.prompt_in[:4] in msg for msg in io_new + io_cache)
            if do_add_cmd:
                # Get cmd number from id
                try:
                    reply = self.si.client.get_reply_msg(self.cmd_id)
                    line_number = reply['content'].get('execution_count', 0)
                except (Empty, KeyError, TypeError):
                    line_number = -1
                s = prettify_execute_intput(
                    line_number, self.cmd, self.si.lang.prompt_in)
                io_new.insert(0, s)

            # Append just new
            _ = [self.si.sync.line_queue.put(s) for s in io_new if s not in io_cache]
            # Update cache
            io_cache = list(set().union(io_cache, io_new))

    def timer_write_console_msgs(self):
        """Write kernel <-> vim messages to console buffer"""
        # Check in
        if self.si.sync.line_queue.empty(): return
        if not self.si.vim.monitor_console and not self.si.vim.verbose: return

        # Get buffer (same indexes as vim)
        if self.si.vim.monitor_console:
            b_nb = int(vim.eval('bufnr("__jupyter_term__")'))
            b = vim.buffers[b_nb]

        # Append mesage to jupyter terminal buffer
        while not self.si.sync.line_queue.empty():
            msg = self.si.sync.line_queue.get_nowait()
            for line in msg.splitlines():
                line = unquote_string(str_to_vim(line))
                if self.si.vim.monitor_console:
                    b.append(line)
                if self.si.vim.verbose:
                    echom(line)

        # Update view (moving cursor)
        if self.si.vim.monitor_console:
            cur_win = vim.eval('win_getid()')
            term_win = vim.eval('bufwinid({})'.format(str(b_nb)))
            vim.command('call win_gotoid({})'.format(term_win))
            vim.command('normal! G')
            vim.command('call win_gotoid({})'.format(cur_win))


def monitor_decorator(fct):
    """Redirect to self.monitor decorator"""
    def wrapper(self, *args, **kwargs):
        self.monitor.monitorable(fct)(self, *args, **kwargs)
    return wrapper
