#!/usr/bin/env python
#
# Find NULL symbols in file, then correlate with the phase reference symbol and
# plot the resulting correlation result.
#
# This will display the Channel Impulse Reference
#
# Copyright (C) 2016
# Matthias P. Braendli, matthias.braendli@mpb.li
# http://www.opendigitalradio.org
# Licence: The MIT License, see LICENCE file

import numpy as np
import matplotlib

# When running on a machine that has no X server running, the normal
# matplotlib backend won't work. In case we are running as a module by cir_measure,
# switch to the Agg backend
# See http://matplotlib.org/faq/howto_faq.html#matplotlib-in-a-web-application-server
# And http://matplotlib.org/examples/api/agg_oo.html#api-agg-oo
if __name__ != "__main__":
    from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
else:
    import matplotlib.pyplot as pp

import matplotlib.figure
import sys

# T = 1/2048000 s
# NULL symbol is 2656 T (about 1.3ms) long.
T_NULL = 2656
# Full transmission frame in TM1 is 96ms = 196608 T.
T_TF = 196608

class CIR_Correlate:
    def __init__(self, iq_filename="", iq_format=None, iq_data=None):
        """Either call with iq_filename, or with iq_data containing
        a np.array with the data.

        This class will then read phase reference from fixed file and
        load IQ data from iq_filename, or use iq_data directly.

        iq_format must be fc64 or u8"""

        if iq_format is None:
            raise ValueError("Incorrect initialisation")

        self.phase_ref = np.fromfile("phasereference.2048000.fc64.iq", np.complex64)

        if iq_format == "u8":
            if iq_filename:
                channel_u8_interleaved = np.fromfile(iq_filename, np.uint8)
            elif iq_data is not None:
                channel_u8_interleaved = iq_data
            else:
                raise ValueError("Must give iq_filename or iq_data")
            channel_u8_iq = channel_u8_interleaved.reshape(int(len(channel_u8_interleaved)/2), 2)
            # This directly converts to fc64
            channel_fc64_unscaled = channel_u8_iq[...,0] + np.complex64(1j) * channel_u8_iq[...,1]
            channel_fc64_scaled = (channel_fc64_unscaled - 127.0) / 128.0
            channel_fc64_dc_comp = channel_fc64_scaled - np.average(channel_fc64_scaled)
            self.channel_out = channel_fc64_dc_comp
        elif iq_format == "fc64":
            if iq_filename:
                self.channel_out = np.fromfile(iq_filename, np.complex64)
            elif iq_data is not None:
                self.channel_out = iq_data
            else:
                raise ValueError("Must give iq_filename or iq_data")
        else:
            raise ValueError("Unsupported format {}".format(iq_format))

        print("  File contains {} samples ({}ms, {} transmission frames)".format(
            len(self.channel_out),
            len(self.channel_out) / 2048000.0,
            len(self.channel_out) / T_TF))

        # Keep track of where the NULL symbols are located
        self.null_symbol_ixs = []

    def calc_one_cir_(self, start_ix):
        """Calculate correlation with phase reference for one start index"""

        print("Correlation at {}".format(start_ix))
        channel = self.channel_out

        # As we do not want to correlate of the whole recording that might be
        # containing several transmission frames, we first look for the null symbol in the
        # first 96ms

        # Calculate power on blocks of length 2656 over the first 96ms. To gain speed,
        # we move the blocks by N samples.
        N = 20
        channel_out_power = np.array([np.abs(channel[start_ix+t:start_ix+t+T_NULL]).sum() for t in range(0, T_TF-T_NULL, N)])

        # Look where the power is smallest, this gives the index where the NULL starts.
        # Because if the subsampling, we need to multiply the index.
        t_null = N * channel_out_power.argmin()

        self.null_symbol_ixs.append(t_null)

        # The synchronisation channel occupies 5208 T and contains NULL symbol and
        # phase reference symbol. The phase reference symbol is 5208 - 2656 = 2552 T
        # long.
        if len(self.phase_ref) != 2552:
            print("Warning: phase ref len is {} != 2552".format(len(self.phase_ref)))

        # We want to correlate our known phase reference symbol against the received
        # signal, and give us some more margin about the exact position of the NULL
        # symbol.

        # We start a bit earlier than the end of the null symbol
        corr_start_ix = t_null + T_NULL - 50

        # In TM1, the longest spacing between carrier components one can allow is
        # around 504 T (246us, or 74km at speed of light). This gives us a limit
        # on the number of correlations it makes sense to do.
        max_component_delay = 1000 # T

        cir = np.array([np.abs(
            np.corrcoef(channel[
                start_ix + corr_start_ix + i:
                start_ix + corr_start_ix + self.phase_ref.size + i
                ] , self.phase_ref)[0,1]
            ) for i in range(max_component_delay)])

        # In order to be able to compare measurements accross transmission frames,
        # we normalise the CIR against channel power
        channel_power = np.abs(channel[start_ix:start_ix+T_TF]).sum()

        return cir / channel_power

    def plot(self, plot_file, title):
        num_correlations = int(len(self.channel_out) / T_TF)

        self.null_symbol_ixs = []

        cirs = np.array([
            self.calc_one_cir_(i * T_TF)
            for i in range(num_correlations) ])

        if plot_file:
            fig = matplotlib.figure.Figure()
            canvas = FigureCanvas(fig)
        else:
            fig = pp.figure()

        fig.suptitle(title)
        ax1 = fig.add_subplot(211)
        ax1.plot(cirs.sum(axis=0))
        ax2 = fig.add_subplot(212)
        ax2.imshow(cirs, aspect='auto')

        if plot_file:
            print("Save to file {}".format(plot_file))
            canvas.print_figure(plot_file)
        else:
            print("Plotting to screen")
            pp.show()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage")
        print(" script [fc64|u8] <filename> [<figure filename>]")
        print(" fc64: file is 32-bit float I + 32-bit float Q")
        print(" u8:   file is 8-bit signed I + 8-bit signed Q")
        print(" if <figure filename> is given, save the figure instead of showing it")
        sys.exit(1)

    print("Reading file")

    file_format = sys.argv[1]
    file_in = sys.argv[2]
    file_figure = None
    if len(sys.argv) == 4:
        file_figure = sys.argv[3]

    cir_corr = CIR_Correlate(file_in, file_format)

    cir_corr.plot(file_figure, "Correlation")

    print("Null symbols at:")
    print("  " + " ".join("{}".format(t_null)
        for t_null in cir_corr.null_symbol_ixs))

    print("Done")


