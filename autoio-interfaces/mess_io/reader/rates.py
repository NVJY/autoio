"""
  Reads the output of a MESS calculation for the
  high-pressure and pressure-dependent rate constants
  corresponding to a given reaction.
"""

import sys
import numpy
import pandas as pd
from phydat import phycon
import autoparse.find as apf


# Functions for getting k(T,P) values from main MESS `RateOut` file
def get_rxn_ktp_dct(out_str,
                    read_fake=False, read_self=False, read_rev=True,
                    filter_kts=True,
                    tmin=None, tmax=None,
                    pmin=None, pmax=None, convert=True):
    """ Read a ktp dictionary for each reaction listed in the MESS output
        file string that requested by the user.

        Pressures in atm.
        K(T)s in cm3/mol.s [bimol] or 1/s [unimol]

        :param output_str: string of lines of MESS output file
        :type output_str: str
        :param label_dct: dictionary to map name from MESS name to alternative
        :type label_dct: dict[str: str]
        :param read_fake: read reactions involving "fake" wells named "Fn"
        :type read_fake: bool
        :param read_self: read reactions where reactant and prod are the same
        :type read_self: bool
        :param read_rev: read reactions in reverse direction
        :type read_ref: bool
        :param filter_kts: filter unphysical, insignificant rate constants
        :type filter_kts: bool

        :rtype dict[float: (float, float)]
    """

    # Get the MESS rxn in the tuple format ((rct,), (prd,), third_body))
    rxns = reactions(out_str,
                     read_fake=read_fake,
                     read_self=read_self,
                     read_rev=read_rev)

    # For each rxn pair, get rate constants, with filtering as indicated
    rxn_ktp_dct = {}
    for rxn in rxns:
        rct, prd = rxn[0][0], rxn[1][0]
        rxn_ktp_dct[rxn] = ktp_dct(out_str, rct, prd,
                                   filter_kts=filter_kts, tmin=tmin,
                                   tmax=tmax, pmin=pmin, pmax=pmax,
                                   convert=convert)
    # Reformat the dictionary keys to follow the tuple of tuples format
    # (if no label_dct was given, the MESS names will be used)
    # rxn_ktp_dct = translate_rxn_names(mess_rxn_ktp_dct, label_dct=label_dct)

    return rxn_ktp_dct


def ktp_dct(output_str, reactant, product, filter_kts=True, tmin=None,
            tmax=None, pmin=None, pmax=None, convert=True):
    """ Parses the MESS output file string for the rate constants [k(T)]s
        for a single reaction for rate constants at all computed pressures,
        including the high-pressure limit.

        Pressures in atm.
        K(T)s in cm3/mol.s [bimol] or 1/s [unimol]

        :param output_str: string of lines of MESS output file
        :type output_str: str
        :param reactant: label for the reactant used in the MESS output
        :type reactant: str
        :param product: label for the product used in the MESS output
        :type product: str
        :rtype dict[float: (float, float)]
    """

    # Build the reaction string found in the MESS output
    reaction = _reaction_header(reactant, product)

    # Get the MESS output lines
    out_lines = output_str.splitlines()

    # Initialize dictionary with high-pressure rate constants
    _ktp_dct = {'high': _highp_kts(out_lines, reaction)}

    # Read the pressures and convert them to atm if needed
    _pressures, _ = pressures(output_str, mess_file='out')

    # Update the dictionary with the pressure-dependent rate constants
    for pressure in (_press for _press in _pressures if _press != 'high'):
        _ktp_dct.update(_pdep_kts(out_lines, reaction, pressure))

    bimol = bool('P' in reactant)
    # Note: filtering is before unit conversion, so bimolthresh is in cm^3.s^-1
    if filter_kts:
        _ktp_dct = filter_ktp_dct(_ktp_dct, bimol, tmin=tmin, tmax=tmax,
                                  pmin=pmin, pmax=pmax)
    if convert:
        _ktp_dct = convert_units(_ktp_dct, bimol)

    return _ktp_dct


def _highp_kts(out_lines, reaction):
    """ Parses the MESS output file string for the rate constants [k(T)]s
        for a single reaction at the high-pressure limit.

        :param out_lines: all of the lines of MESS output
        :type out_lines: list(str)
        :param reaction: string matching reaction line in MESS output
        :type reaction: str
        :return rate_constants: all high-P rate constants for the reaction
        :rtype list(float)
    """

    # Find where the block of text where the high-pressure rates exist
    block_str = ('High Pressure Rate Coefficients ' +
                 '(Temperature-Species Rate Tables):')
    for i, line in enumerate(out_lines):
        if block_str in line:
            block_start = i
            break

    # Get the high-pressure rate constants
    rate_constants = []
    for i in range(block_start, len(out_lines)):
        if reaction in out_lines[i]:
            rate_const_block_start = i
            rate_constants = _parse_rate_constants(
                out_lines, rate_const_block_start, reaction)
            break

    return rate_constants


def _pdep_kts(out_lines, reaction, pressure):
    """ Parses the MESS output file string for the rate constants [k(T,P)]s
        for a single reaction at a given numerical pressure, P.

        :param out_lines: all of the lines of MESS output
        :type out_lines: list(str)
        :param reaction: string matching reaction line in MESS output
        :type reaction: str
        :param pressure: pressure that k(T,P)s will be read for
        :type pressure: float
        :return rate_constants: k(T,P)s for the reaction at given pressure
        :rtype list(float)
    """

    # Find where the block of text where the pressure-dependent rates exist
    block_str = ('Temperature-Species Rate Tables:')

    pdep_dct = {}
    for i, line in enumerate(out_lines):
        if block_str in line:
            for j in range(i, len(out_lines)):
                if 'Temperature-Pressure Rate Tables' in out_lines[j]:
                    break
                if reaction in out_lines[j]:
                    mess_press = float(out_lines[j-2].strip().split()[2])
                    mess_punit = out_lines[j-2].strip().split()[3]
                    if numpy.isclose(mess_press, pressure):
                        conv_pressure = _convert_pressure(pressure, mess_punit)
                        pdep_dct[conv_pressure] = _parse_rate_constants(
                            out_lines, j, reaction)
                        break

    return pdep_dct


def _parse_rate_constants(out_lines, block_start, reaction):
    """ Parses specific rate constants from the correct column
        in the MESS output file string.

        :param out_lines: all of the lines of MESS output
        :type out_lines: list(str)
        :param block_start: line num corresponding to reaction and pressure
        :type block_start: int
        :param reaction: string matching reaction line in MESS output
        :type reaction: str
        :return rate_constants: all rate constants for the reaction
        :rtype: list(str, float)
    """

    # Find the column corresponding to the reaction
    reaction_col = 0
    reaction_headers = out_lines[block_start].strip().split()
    for i, reaction_header in enumerate(reaction_headers):
        if reaction == reaction_header:
            reaction_col = i
            break

    # Parse the following lines and store the constants in a list
    temps, kts = [], []
    for i in range(block_start+1, len(out_lines)):
        if out_lines[i].strip() == '':
            break
        temps.append(out_lines[i].strip().split()[0])
        kts.append(out_lines[i].strip().split()[reaction_col])

    # Convert temps and rate constants to floats and combine values
    # only do so if the rate constant is defined (i.e., not '***')
    fin_temps = tuple(float(temp) for temp in temps)
    fin_kts = ()
    for kt_i in kts:
        new_kt = float(kt_i) if kt_i != '***' else None
        fin_kts += (new_kt,)

    return (fin_temps, fin_kts)


# Functions for getting k(E)s and density-of-states from
# main MESS `MicroRateOut` file
def ke_dct(output_str, reactant, product):
    """ Parses the MESS output file string for the microcanonical
        rate constants [k(E)]s for a single reaction.

        :param output_str: string of lines of MESS output file
        :type output_str: str
        :param reactant: label for the reactant used in the MESS output
        :type reactant: str
        :param product: label for the product used in the MESS output
        :type product: str
        :return rate_constants: all high-P rate constants for the reaction
        :rtype dict[float: float]
    """

    # Form string for reaction header using reactant and product name
    reaction = _reaction_header(reactant, product)

    # Break up the file into lines
    out_lines = output_str.split('\n')

    # Determine col idx where reaction is
    head = out_lines[0].replace('E, kcal/mol', 'E').replace('D, mol/kcal', 'D')
    headers = head.split()
    col_idx = headers.index(reaction)

    _ke_dct = {0.0: 0.0}
    for i, line in enumerate(out_lines):
        if i not in (0, 1):
            tmp = line.strip().split()
            if tmp:
                _ke_dct[float(tmp[0])] = float(tmp[col_idx])

    return _ke_dct


def dos_rovib(ke_ped_out):
    """ Read the microcanonical pedoutput file and extracts rovibrational density
        of states of each fragment as a function of the energy

        units: kcal/mol, and for dos mol/kcal

        :param ke_ped_out: string of lines of microcanonical rates output file
        :type ke_ped_out: str

        :return dos_df: dataframe(columns:prod1, prod2, rows:energy [kcal/mol])
                        with the density of states
        :rtype dos_df: dataframe(float)
    """
    # apf.where data of interest are
    ke_lines = ke_ped_out.splitlines()

    i_in = apf.where_in(
        'Bimolecular fragments density of states:', ke_lines)[0]+2
    _labels = ke_lines[i_in-1].strip().split()[2:]
    en_dos_all = numpy.array(
        [line.strip().split() for line in ke_lines[i_in:]], dtype=float).T
    energy = en_dos_all[:][0]
    dos_all = en_dos_all[:][1:].T

    dos_rovib_df = pd.DataFrame(dos_all, index=energy, columns=_labels)
    # drop potentially duplicate columns
    dos_rovib_df = dos_rovib_df.T.drop_duplicates().T

    return dos_rovib_df


# Functions for getting barrier heights and corresponding reactants, products
# not tested because currently unused
def energies(output_str):
    """ Parses the MESS output and gets the energies of all species
        :param output_str: string of lines of MESS output file
        :type output_str: str

        :return species_en, barriers_en: species and barrier energy in kcal/mol
        :rtype series(index=name), series(index=(reac,prod))
    """

    # Break up the file into lines
    out_lines = numpy.array(output_str.split('\n\n'))
    headers = ['Wells', 'Bimolecular Products',
               'Well-to-Bimolecular', 'Well-to-Well']
    # Determine where block is
    block_indexes = apf.where_in_any(headers, out_lines)

    # preallocations
    _species = []
    _species_ene = []
    _barriers = []
    _barriers_ene = []

    for i in block_indexes:
        block = out_lines[i]
        lines = block.splitlines()

        if 'Wells' in block or 'Bimolecular Products' in block:
            for line in lines[2:]:
                spc, ene = line.strip().split()[0:2]
                _species.append(spc)
                _species_ene.append(float(ene))

    species_ene_s = pd.Series(_species_ene, index=_species)

    for i in block_indexes:
        block = out_lines[i]
        lines = block.splitlines()
        if 'Well-to-Bimolecular' in block:
            for line in lines[2:]:
                _, ene, reac, _, prod = line.strip().split()
                _barriers.append((reac, prod))
                _barriers.append((prod, reac))
                # relative energy
                _barriers_ene.append(float(ene)-species_ene_s[reac])
                _barriers_ene.append(float(ene)-species_ene_s[prod])

        if 'Well-to-Well' in block:
            for line in lines[2:]:
                _, ene, reac, _, prod, _ = line.strip().split()
                _barriers.append((reac, prod))
                _barriers.append((prod, reac))
                _barriers_ene.append(float(ene)-species_ene_s[reac])
                _barriers_ene.append(float(ene)-species_ene_s[prod])

    barriers_ene_s = pd.Series(_barriers_ene, index=_barriers)

    return species_ene_s, barriers_ene_s


def barriers(barriers_ene_s, species_ene_s, reac, prod):
    """ Extract fw and bw energy barrier for reaction reac->prod
        if barrier not found, save the DE of the reaction
    """
    findreac = [reac == key[0] for key in barriers_ene_s.keys()]
    findprod = [prod == key[1] for key in barriers_ene_s.keys()]
    findreac_rev = [reac == key[1] for key in barriers_ene_s.keys()]
    findprod_rev = [prod == key[0] for key in barriers_ene_s.keys()]

    if (reac, prod) in barriers_ene_s.keys():
        dene_fw = barriers_ene_s[(reac, prod)]
        # DW_BW = barriers_ene_s[(prod, reac)]

    elif (
        any(findreac) or any(findreac_rev) and
        any(findprod) or any(findprod_rev)
         ):
        # check if you have reac->wr->wp->prod like in habs
        connect_reac = numpy.array(list(barriers_ene_s.keys()))[findreac]
        fromreac = [p[1] for p in connect_reac]
        connect_prod = numpy.array(list(barriers_ene_s.keys()))[findprod]
        fromprod = [r[0] for r in connect_prod]
        possible_index = [(p, r) for p in fromreac for r in fromprod]
        possible_index += [(reac, p) for p in fromprod]
        possible_index += [(r, prod) for r in fromreac]

        flag = 0

        for idx in possible_index:

            try:
                delta_ene = barriers_ene_s[idx]
                # barriers like r=>wr=>wp=>p
                dene_fw = delta_ene - barriers_ene_s[(idx[0], reac)]
                dene_bw = barriers_ene_s[(idx[1], idx[0])] - \
                    barriers_ene_s[(idx[1], prod)]
                flag = 1
            except (KeyError, ValueError):
                try:
                    # barriers like r=>wr=>p
                    # reacs=>wr
                    dene_fw = barriers_ene_s[(idx[0], prod)] - \
                        barriers_ene_s[(idx[0], reac)]

                    dene_bw = dene_fw + barriers_ene_s[(prod, idx[0])]
                    flag = 1
                except (KeyError, ValueError):
                    continue

        if flag == 0:
            print('*Warning: indirect connection between '
                  f'{reac} and {prod} not found')
            print('saving the DE instead \n')
            try:
                dene_fw = species_ene_s[prod] - species_ene_s[reac]
                dene_bw = species_ene_s[reac] - species_ene_s[prod]
            except KeyError:
                print('*Error: species '
                      f'{reac} and {prod} not found. Now exiting \n')
    else:
        print(f'*Error: species {reac} and {prod} not found')
        sys.exit()

    return dene_fw, dene_bw


# Functions to read temperatures and pressures
def temperatures(file_str, mess_file='out'):
    """ Get temps
    """

    if mess_file == 'out':
        temps = _temperatures_output_string(file_str)
    elif mess_file == 'inp':
        temps = _temperatures_input_string(file_str)
    else:
        temps = ()

    return temps


def pressures(file_str, mess_file='out'):
    """ Get pressures
    """

    if mess_file == 'out':
        _pressures = _pressures_output_string(file_str)
    elif mess_file == 'inp':
        _pressures = _pressures_input_string(file_str)
    else:
        _pressures = ()

    return _pressures


def _temperatures_input_string(input_str):
    """ Reads the temperatures from the MESS input file string
        that were used in the master-equation calculation.
        :param input_str: string of lines of MESS input file
        :type input_str: str
        :return temperatures: temperatures in the input
        :rtype: list(float)
        :return temperature_unit: unit of the temperatures in the input
        :rtype: str
    """

    # Get the MESS input lines
    mess_lines = input_str.splitlines()
    for line in mess_lines:
        if 'TemperatureList' in line:
            temps = tuple(float(val) for val in line.strip().split()[1:])
            temp_unit = line.strip().split('[')[1].split(']')[0]
            break

    return temps, temp_unit


def _temperatures_output_string(output_str):
    """ Reads the temperatures from the MESS output file string
        that were used in the master-equation calculation.
        :param output_str: string of lines of MESS output file
        :type output_str: str
        :return temperatures: temperatures in the output
        :rtype: list(float)
        :return temperature_unit: unit of the temperatures in the output
        :rtype: str
    """

    # Get the MESS output lines
    mess_lines = output_str.splitlines()

    # Find the block of lines where the temperatures can be read
    temp_str = 'Pressure-Species Rate Tables:'
    for i, line in enumerate(mess_lines):
        if temp_str in line:
            block_start = i
            break

    # Read the temperatures
    temps = []
    for i in range(block_start, len(mess_lines)):
        if 'Temperature =' in mess_lines[i]:
            tmp = mess_lines[i].strip().split()
            temps.append(float(tmp[2]))
    temps = list(set(temps))
    temps.sort()

    # Read unit
    for i in range(block_start, len(mess_lines)):
        if 'Temperature =' in mess_lines[i]:
            temp_unit = mess_lines[i].strip().split()[3]
            break

    return tuple(temps), temp_unit


def _pressures_input_string(input_str):
    """ Reads the pressures from the MESS input file string
        that were used in the master-equation calculation.
        :param input_str: string of lines of MESS input file
        :type input_str: str
        :return pressures: pressures in the input
        :rtype: list(str, float)
        :return pressure_unit: unit of the pressures in the input
        :rtype: str
    """

    # Get the MESS input lines
    mess_lines = input_str.splitlines()
    for line in mess_lines:
        if 'PressureList' in line:
            _pressures = [float(val) for val in line.strip().split()[1:]]
            pressure_unit = line.strip().split('[')[1].split(']')[0]
            break

    # Append high pressure
    _pressures.append('high')

    return tuple(_pressures), pressure_unit


def _pressures_output_string(output_str):
    """ Reads the pressures from the MESS output file string
        that were used in the master-equation calculation.
        :param output_str: string of lines of MESS output file
        :type output_str: str
        :return pressures: pressures in the output
        :rtype: list(str, float)
        :return pressure_unit: unit of the pressures in the output
        :rtype: str
    """

    # Get the MESS output lines
    mess_lines = output_str.splitlines()

    # Find the block of lines where the pressures can be read
    pressure_str = 'Pressure-Species Rate Tables:'
    for i, line in enumerate(mess_lines):
        if pressure_str in line:
            block_start = i
            break

    # Read the pressures
    _pressures = []
    for i in range(block_start, len(mess_lines)):
        if 'P(' in mess_lines[i]:
            pressure_unit = mess_lines[i].strip().split('(')[1].split(')')[0]
            pressure_start = i+1
            for j in range(pressure_start, len(mess_lines)):
                if 'O-O' in mess_lines[j]:
                    break
                tmp = mess_lines[j].strip().split()
                _pressures.append(float(tmp[0]))
            break

    # Append high pressure
    _pressures.append('high')

    return tuple(_pressures), pressure_unit


def _convert_pressure(pressure, pressure_unit):
    """ Convert a set of pressures using the pressure unit, accounting
        for high-pressure in list

        :param pressure: pressures to convert
        :type pressure: tuple(float, str)
        :param pressure_unit: unit of pressures
        :type pressure_unit: str
        :rtype: tuple(float, str)
    """

    if pressure != 'high':
        if pressure_unit == 'atm':
            conv = 1.0
        elif pressure_unit == 'torr':
            conv = phycon.TORR2ATM
        elif pressure_unit == 'bar':
            conv = phycon.BAR2ATM
        pressure *= conv

    return pressure


# Read the labels for all species and reactions
def reactions(out_str,
              third_body=(None,),
              read_fake=False, read_self=False, read_rev=True):
    """ Read the reactions from the output file.

        Currently, we assume we don't care about the third body
        and have the user pass it.

        Returns the reactions in tuple list (reacs, prods, third_body)
        where reacs and prods are tuples

        Ignores 'Capture' reactions
    """

    # Read all of the reactions out of the file
    init_rxns = ()
    for line in out_str.splitlines():
        if 'T(K)' in line and '->' in line:
            init_rxns += tuple(line.strip().split()[1:])

    # Remove duplcates while preserving order
    init_rxns = tuple(n for i, n in enumerate(init_rxns)
                      if n not in init_rxns[:i])

    # Remove capture reactions
    init_rxns = tuple(rxn for rxn in init_rxns
                      if rxn != 'Capture')

    # Build list of reaction pairs: rct->prd = (rct, prd)
    # Filter out reaction as necessary
    rxn_pairs = ()
    for rxn in init_rxns:
        [rct, prd] = rxn.split('->')
        if not read_fake:
            if 'F' in rxn or 'B' in rxn:
                continue
        if not read_self:
            if rct == prd:
                continue
        if prd:  # removes rct->  reactions in output
            rxn_pairs += ((rct, prd),)

    # Remove reverse reactions, if requested
    if read_rev:
        sort_rxn_pairs = rxn_pairs
    else:
        sort_rxn_pairs = ()
        for pair in rxn_pairs:
            rct, prd = pair
            if (rct, prd) in sort_rxn_pairs or (prd, rct) in sort_rxn_pairs:
                continue
            sort_rxn_pairs += ((rct, prd),)

    # Add the third body to the sorted pairs
    fin_rxns = ()
    for rxn in sort_rxn_pairs:
        rct, prd = rxn
        fin_rxns += (
            ((rct,), (prd,), third_body),
        )

    return fin_rxns


def labels(file_str, read_fake=False, mess_file='out'):
    """ Read the labels out of a MESS file
    """

    if mess_file == 'out':
        lbls = _labels_output_string(file_str)
    elif mess_file == 'inp':
        lbls = _labels_input_string(file_str)
    else:
        lbls = ()

    if not read_fake:
        lbls = tuple(lbl for lbl in lbls
                     if 'F' not in lbl and 'f' not in lbl)

    return lbls


def _labels_input_string(inp_str):
    """ Read the labels out of a MESS input file
    """

    def _read_label(line, header):
        """ Get a labe from a line
        """
        lbl = None
        idx = 2 if header != 'Barrier' else 4
        line_lst = line.split()
        if len(line_lst) == idx and '!' not in line:
            lbl = line_lst[idx]
        return lbl

    lbls = ()
    for line in inp_str.splitlines():
        if 'Well ' in line:
            lbls += (_read_label(line, 'Well'),)
        elif 'Bimolecular ' in line:
            lbls += (_read_label(line, 'Bimolecular'),)
        elif 'Barrier ' in line:
            lbls += (_read_label(line, 'Barrier'),)

    return lbls


def _labels_output_string(out_str):
    """ Read the labels out of a MESS input file
    """

    lbls = []
    for line in out_str.splitlines():
        if 'T(K)' in line and '->' not in line:
            rxns = line.strip().split()[1:]
            line_lbls = [rxn.split('->') for rxn in rxns]
            line_lbls = [lbl for sublst in line_lbls for lbl in sublst]
            lbls.extend(line_lbls)

    # Remove duplicates and make lst a tuple
    lbls = tuple(set(lbls))

    return lbls


# Helper functions
def _reaction_header(reactant, product):
    return reactant + '->' + product


def filter_ktp_dct(_ktp_dct, bimol,
                   tmin=None, tmax=None, pmin=None, pmax=None):
    """ Filters out bad or undesired rate constants from a ktp dictionary
    """

    def get_valid_tk(temps, kts, bimol, tmin=None, tmax=None,
                     bimolthresh=1.0e-24):
        """ Takes in lists of temperature-rate constant pairs [T,k(T)]
            and removes invalid pairs for which
            (1) k(T) < 0
            (2) k(T) is undefined from Master Equation (i.e. k(T) is None)
            (3) k(T) < some threshold for bimolecular reactions, or
            (4) T is outside the cutoff

            :param temps: temperatures at which rate constants are defined (K)
            :type temps: list(float)
            :param kts: rate constants (s-1 or cm^3.s-1)
            :type kts: list(str, float)
            :param bimol: whether or not the reaction is bimolecular
            :type bimol: Bool
            :param bimolthresh: threshold below which bimolecular rate
                constants will be removed (cm^3.s^-1)
            :type bimolthresh: float
            :return valid_t: List of vaild temperatures
            :return valid_k: List of vaild rate constants
            :rtype: (numpy.ndarray, numpy.ndarray)
            """

        # Set max temperature
        if tmax is None:
            tmax = max(temps)
        else:
            assert tmax in temps, (f'{tmax} not in temps: {temps}')

        # Set min temperature to user input, if none use either
        # min of input temperatures or
        # if negative kts are found, set min temp to be just above highest neg.
        max_neg_idx = None
        for kt_idx, sing_kt in enumerate(kts):
            # find idx for max temperature for which kt is negative, if any
            float_sing_kt = float(sing_kt) if sing_kt is not None else 1.0
            if float_sing_kt < 0.0:
                max_neg_idx = kt_idx
        
        #   Otherwise, use requested tmin value or minimum of input temps 
        # Set tmin to None (i.e., no valid k(T)) if highest T has neg. k(T)
        if max_neg_idx is not None:
            # If negative values found:
            #   Set tmin to highest T where k(T) is non-negative
            if max_neg_idx+1 < len(temps):
                tmin = temps[max_neg_idx+1]
            else:
                tmin = None
        else:
            # Otherwise, use requested tmin value or minimum of input temps 
            if tmin is None:
                tmin = min(temps)
            else:
                assert tmin in temps, (f'{tmin} not in temps: {temps}')

        # Grab the temperature, rate constant pairs which correspond to
        # temp > 0, temp within tmin and tmax, rate constant defined (not ***)
        valid_t, valid_k = [], []
        if tmin is not None and tmax is not None:
            for temp, sing_kt in zip(temps, kts):
                if sing_kt is None:
                    continue
                kthresh = 0.0 if not bimol else bimolthresh
                if float(sing_kt) > kthresh and tmin <= temp <= tmax:
                    valid_t.append(temp)
                    valid_k.append(sing_kt)

        # Convert the lists to numpy arrays
        valid_t = numpy.array(valid_t, dtype=numpy.float64)
        valid_k = numpy.array(valid_k, dtype=numpy.float64)

        return valid_t, valid_k

    # Filter the kts based on temps, negatives, None, and bimolthresh
    filt_ktp_dct = {}
    for pressure, (temps, kts) in _ktp_dct.items():
        filt_temps, filt_kts = get_valid_tk(temps, kts, bimol, tmin, tmax)
        if filt_kts.size > 0:
            filt_ktp_dct[pressure] = (filt_temps, filt_kts)

    # Remove undesired pressures if pmin and/or pmax were given (leaves 'high'
    # untouched if it is present)
    _pressures = tuple(pressure for pressure in filt_ktp_dct
                       if pressure != 'high')
    for pressure in _pressures:
        if pmin is not None:
            if pressure < pmin:
                filt_ktp_dct.pop(pressure)
        if pmax is not None:
            if pressure > pmax:
                filt_ktp_dct.pop(pressure)

    return filt_ktp_dct


def relabel(rxn_ktp_dct, label_dct):
    """ Relabel the rxn ktp dictionaries using the label dictionary
    """

    def _relabel(lbl, label_dct):
        """ a
        """
        if lbl in label_dct:
            relbl = tuple(label_dct[lbl].split('+'))
        else:
            relbl = (lbl,)
        return relbl

    relab_rxn_ktp_dct = {}
    for rxn, _ktp_dct in rxn_ktp_dct.items():
        rcts, prds, thirdbody = rxn

        relab_rcts = ()
        for rct in rcts:
            relab_rcts += _relabel(rct, label_dct)
        relab_prds = ()
        for prd in prds:
            relab_prds += _relabel(prd, label_dct)

        relab_rxn_ktp_dct[(relab_rcts, relab_prds, thirdbody)] = _ktp_dct

    return relab_rxn_ktp_dct


def convert_units(_ktp_dct, bimol):
    """ Convert units from cm^3.s^-1 to cm^3.mol^-1.s^-1 if rxn is bimolecular
    """

    conv_ktp_dct = {}
    for pressure, (temps, kts) in _ktp_dct.items():
        if bimol:
            kts *= phycon.NAVO
        conv_ktp_dct[pressure] = (temps, kts)

    return conv_ktp_dct
