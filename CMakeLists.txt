cmake_minimum_required(VERSION 3.21)
project(pyobs_qhyccd LANGUAGES CXX)

# --- Ensure we use the build environment Python ---
set(Python3_FIND_VIRTUALENV ONLY)
set(Python3_FIND_STRATEGY LOCATION)

find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)

# --- Paths ---
set(PYX_FILE "${CMAKE_CURRENT_SOURCE_DIR}/pyobs_qhyccd/qhyccddriver.pyx")
set(CXX_FILE "${CMAKE_CURRENT_BINARY_DIR}/qhyccddriver.cpp")

# --- Run Cython manually ---
add_custom_command(
  OUTPUT ${CXX_FILE}
  COMMAND "${Python3_EXECUTABLE}" -m cython
          ${PYX_FILE}
          --output-file ${CXX_FILE}
          --cplus
  DEPENDS ${PYX_FILE}
  COMMENT "Running Cython on qhyccddriver.pyx"
)

# --- Get NumPy include dir ---
execute_process(
  COMMAND "${Python3_EXECUTABLE}" -c
          "import numpy; print(numpy.get_include())"
  OUTPUT_VARIABLE NUMPY_INCLUDE_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
)

# --- Build extension module ---
add_library(pyobs_qhyccd MODULE ${CXX_FILE})
set_source_files_properties(${CXX_FILE} PROPERTIES LANGUAGE CXX)
target_include_directories(pyobs_qhyccd PRIVATE
  ${Python3_INCLUDE_DIRS}
  ${NUMPY_INCLUDE_DIR}
)

# --- Correct Python module naming (VERY IMPORTANT) ---
execute_process(
  COMMAND "${Python3_EXECUTABLE}" -c
          "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))"
  OUTPUT_VARIABLE PY_EXT_SUFFIX
  OUTPUT_STRIP_TRAILING_WHITESPACE
)
set_target_properties(pyobs_qhyccd PROPERTIES
  PREFIX ""
  OUTPUT_NAME "qhyccddriver"
  SUFFIX "${PY_EXT_SUFFIX}"
)
message(STATUS "ext: ${PY_EXT_SUFFIX}")

# --- QHYCCD ---
target_include_directories(pyobs_qhyccd PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/lib/usr/local/include/
)

# --- Install into package ---
install(TARGETS pyobs_qhyccd
  LIBRARY DESTINATION ${SKBUILD_PROJECT_NAME}
)
