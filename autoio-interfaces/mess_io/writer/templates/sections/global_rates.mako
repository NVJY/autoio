!===================================================
!  GLOBAL KEYWORDS
!===================================================
TemperatureList[K]                     ${temperatures}
PressureList[atm]                      ${pressures}
!
ModelEnergyLimit[kcal/mol]             ${model_ene_limit}
EnergyStepOverTemperature              ${ene_stepover_temp}
% if excess_ene_temp is not None:
ExcessEnergyOverTemperature            ${excess_ene_temp}
% endif
!
CalculationMethod                      ${calculation_method}
% if calculation_method == 'well-reduction':
WellReductionThreshold                 ${well_reduction_thresh} 
% endif
!
WellCutoff                             10
% if well_extension is not None:
WellExtension                          ${well_extension}
% endif
ChemicalEigenvalueMax                  0.2
!
ReductionMethod                        diagonalization 
% if ped_spc_str is not None:
!
PEDOutput                              ${ped_outname}
PEDSpecies                             ${ped_spc_str}
% endif
% if hot_ene_str is not None:
!
HotEnergies[kcal/mol]                  ${nhot}
${hot_ene_str}
% endif
% if micro_out_params is not None:
!
MicroRateOutput                        ${ke_outname}
MicroEnerMin[kcal/mol]                 ${micro_out_params[0]}
MicroEnerMax[kcal/mol]                 ${micro_out_params[1]}
MicroEnerStep[kcal/mol]                ${micro_out_params[2]}
% endif
!
AtomDistanceMin[angstrom]              0.68793
!
RateOutput                             ${ktp_outname}
% if float_type == 'quadruple':
!
FloatType                              dd
% endif
