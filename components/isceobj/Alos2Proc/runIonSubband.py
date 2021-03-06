#
# Author: Cunren Liang
# Copyright 2015-present, NASA-JPL/Caltech
#

import os
import logging

import isceobj
from isceobj.Constants import SPEED_OF_LIGHT

logger = logging.getLogger('isce.alos2insar.runIonSubband')

def runIonSubband(self):
    '''create subband interferograms
    '''
    catalog = isceobj.Catalog.createCatalog(self._insar.procDoc.name)
    self.updateParamemetersFromUser()

    if not self.doIon:
        catalog.printToLog(logger, "runIonSubband")
        self._insar.procDoc.addAllFromCatalog(catalog)
        return

    masterTrack = self._insar.loadTrack(master=True)
    slaveTrack = self._insar.loadTrack(master=False)

    #using 1/3, 1/3, 1/3 band split
    radarWavelength = masterTrack.radarWavelength
    rangeBandwidth = masterTrack.frames[0].swaths[0].rangeBandwidth
    rangeSamplingRate = masterTrack.frames[0].swaths[0].rangeSamplingRate
    radarWavelengthLower = SPEED_OF_LIGHT/(SPEED_OF_LIGHT / radarWavelength - rangeBandwidth / 3.0)
    radarWavelengthUpper = SPEED_OF_LIGHT/(SPEED_OF_LIGHT / radarWavelength + rangeBandwidth / 3.0)
    subbandRadarWavelength = [radarWavelengthLower, radarWavelengthUpper]
    subbandBandWidth = [rangeBandwidth / 3.0 / rangeSamplingRate, rangeBandwidth / 3.0 / rangeSamplingRate]
    subbandFrequencyCenter = [-rangeBandwidth / 3.0 / rangeSamplingRate, rangeBandwidth / 3.0 / rangeSamplingRate]

    subbandPrefix = ['lower', 'upper']

    '''
    ionDir = {
        ionDir['swathMosaic'] : 'mosaic',
        ionDir['insar'] : 'insar',
        ionDir['ion'] : 'ion',
        ionDir['subband'] : ['lower', 'upper'],
        ionDir['ionCal'] : 'ion_cal'
        }
    '''
    #define upper level directory names
    ionDir = defineIonDir()


    self._insar.subbandRadarWavelength = subbandRadarWavelength


    ############################################################
    # STEP 1. create directories
    ############################################################
    #create and enter 'ion' directory
    #after finishing each step, we are in this directory
    if not os.path.exists(ionDir['ion']):
        os.makedirs(ionDir['ion'])
    os.chdir(ionDir['ion'])

    #create insar processing directories
    for k in range(2):
        subbandDir = ionDir['subband'][k]
        for i, frameNumber in enumerate(self._insar.masterFrames):
            frameDir = 'f{}_{}'.format(i+1, frameNumber)
            for j, swathNumber in enumerate(range(self._insar.startingSwath, self._insar.endingSwath + 1)):
                swathDir = 's{}'.format(swathNumber)
                fullDir = os.path.join(subbandDir, frameDir, swathDir)
                if not os.path.exists(fullDir):
                    os.makedirs(fullDir)

    #create ionospheric phase directory
    if not os.path.exists(ionDir['ionCal']):
        os.makedirs(ionDir['ionCal'])


    ############################################################
    # STEP 2. create subband interferograms
    ############################################################
    import numpy as np
    import stdproc
    from iscesys.StdOEL.StdOELPy import create_writer
    from isceobj.Alos2Proc.Alos2ProcPublic import readOffset
    from contrib.alos2proc.alos2proc import rg_filter

    for i, frameNumber in enumerate(self._insar.masterFrames):
        frameDir = 'f{}_{}'.format(i+1, frameNumber)
        for j, swathNumber in enumerate(range(self._insar.startingSwath, self._insar.endingSwath + 1)):
            swathDir = 's{}'.format(swathNumber)
            #filter master and slave images
            for slcx in [self._insar.masterSlc, self._insar.slaveSlc]:
                slc = os.path.join('../', frameDir, swathDir, slcx)
                slcLower = os.path.join(ionDir['subband'][0], frameDir, swathDir, slcx)
                slcUpper = os.path.join(ionDir['subband'][1], frameDir, swathDir, slcx)
                rg_filter(slc, 2, 
                    [slcLower, slcUpper], 
                    subbandBandWidth, 
                    subbandFrequencyCenter, 
                    257, 2048, 0.1, 0, 0.0)
            #resample
            for k in range(2):
                os.chdir(os.path.join(ionDir['subband'][k], frameDir, swathDir))
                #recreate xml file to remove the file path
                #can also use fixImageXml.py?
                for x in [self._insar.masterSlc, self._insar.slaveSlc]:
                    img = isceobj.createSlcImage()
                    img.load(x + '.xml')
                    img.setFilename(x)
                    img.extraFilename = x + '.vrt'
                    img.setAccessMode('READ')
                    img.renderHdr()

                #############################################
                #1. form interferogram
                #############################################
                masterSwath = masterTrack.frames[i].swaths[j]
                slaveSwath = slaveTrack.frames[i].swaths[j]

                refinedOffsets = readOffset(os.path.join('../../../../', frameDir, swathDir, 'cull.off'))
                intWidth = int(masterSwath.numberOfSamples / self._insar.numberRangeLooks1)
                intLength = int(masterSwath.numberOfLines / self._insar.numberAzimuthLooks1)
                dopplerVsPixel = [i/slaveSwath.prf for i in slaveSwath.dopplerVsPixel]

                #master slc
                mSLC = isceobj.createSlcImage()
                mSLC.load(self._insar.masterSlc+'.xml')
                mSLC.setAccessMode('read')
                mSLC.createImage()

                #slave slc
                sSLC = isceobj.createSlcImage()
                sSLC.load(self._insar.slaveSlc+'.xml')
                sSLC.setAccessMode('read')
                sSLC.createImage()

                #interferogram
                interf = isceobj.createIntImage()
                interf.setFilename(self._insar.interferogram)
                interf.setWidth(intWidth)
                interf.setAccessMode('write')
                interf.createImage()

                #amplitdue
                amplitude = isceobj.createAmpImage()
                amplitude.setFilename(self._insar.amplitude)
                amplitude.setWidth(intWidth)
                amplitude.setAccessMode('write')
                amplitude.createImage()

                #create a writer for resamp
                stdWriter = create_writer("log", "", True, filename="resamp.log")
                stdWriter.setFileTag("resamp", "log")
                stdWriter.setFileTag("resamp", "err")
                stdWriter.setFileTag("resamp", "out")


                #set up resampling program now
                #The setting has been compared with resamp_roi's setting in ROI_pac item by item.
                #The two kinds of setting are exactly the same. The number of setting items are
                #exactly the same
                objResamp = stdproc.createResamp()
                objResamp.wireInputPort(name='offsets', object=refinedOffsets)
                objResamp.stdWriter = stdWriter
                objResamp.setNumberFitCoefficients(6)
                objResamp.setNumberRangeBin1(masterSwath.numberOfSamples)
                objResamp.setNumberRangeBin2(slaveSwath.numberOfSamples)    
                objResamp.setStartLine(1)
                objResamp.setNumberLines(masterSwath.numberOfLines)
                objResamp.setFirstLineOffset(1)
                objResamp.setDopplerCentroidCoefficients(dopplerVsPixel)
                objResamp.setRadarWavelength(subbandRadarWavelength[k])
                objResamp.setSlantRangePixelSpacing(slaveSwath.rangePixelSize)
                objResamp.setNumberRangeLooks(self._insar.numberRangeLooks1)
                objResamp.setNumberAzimuthLooks(self._insar.numberAzimuthLooks1)
                objResamp.setFlattenWithOffsetFitFlag(0)
                objResamp.resamp(mSLC, sSLC, interf, amplitude) 
                
                #finialize images
                mSLC.finalizeImage()
                sSLC.finalizeImage()
                interf.finalizeImage()
                amplitude.finalizeImage()
                stdWriter.finalize()

                #############################################
                #2. trim amplitude
                #############################################
                #using memmap instead, which should be faster, since we only have a few pixels to change
                amp=np.memmap(self._insar.amplitude, dtype='complex64', mode='r+', shape=(intLength, intWidth))
                index = np.nonzero( (np.real(amp)==0) + (np.imag(amp)==0) )
                amp[index]=0

                #Deletion flushes memory changes to disk before removing the object:
                del amp

                #############################################
                #3. delete subband slcs
                #############################################
                os.remove(self._insar.masterSlc)
                os.remove(self._insar.masterSlc + '.vrt')
                os.remove(self._insar.masterSlc + '.xml')
                os.remove(self._insar.slaveSlc)
                os.remove(self._insar.slaveSlc + '.vrt')
                os.remove(self._insar.slaveSlc + '.xml')

                os.chdir('../../../')


    ############################################################
    # STEP 3. mosaic swaths
    ############################################################
    from isceobj.Alos2Proc.runSwathMosaic import swathMosaic
    from isceobj.Alos2Proc.Alos2ProcPublic import create_xml

    for k in range(2):
        os.chdir(ionDir['subband'][k])
        for i, frameNumber in enumerate(self._insar.masterFrames):
            frameDir = 'f{}_{}'.format(i+1, frameNumber)
            os.chdir(frameDir)

            mosaicDir = ionDir['swathMosaic']
            if not os.path.exists(mosaicDir):
                os.makedirs(mosaicDir)
            os.chdir(mosaicDir)

            if not (
                   ((self._insar.modeCombination == 21) or \
                    (self._insar.modeCombination == 22) or \
                    (self._insar.modeCombination == 31) or \
                    (self._insar.modeCombination == 32)) 
                   and
                   (self._insar.endingSwath-self._insar.startingSwath+1 > 1)
                   ):
                import shutil
                swathDir = 's{}'.format(masterTrack.frames[i].swaths[0].swathNumber)
                
                # if not os.path.isfile(self._insar.interferogram):
                #     os.symlink(os.path.join('../', swathDir, self._insar.interferogram), self._insar.interferogram)
                # shutil.copy2(os.path.join('../', swathDir, self._insar.interferogram+'.vrt'), self._insar.interferogram+'.vrt')
                # shutil.copy2(os.path.join('../', swathDir, self._insar.interferogram+'.xml'), self._insar.interferogram+'.xml')
                # if not os.path.isfile(self._insar.amplitude):
                #     os.symlink(os.path.join('../', swathDir, self._insar.amplitude), self._insar.amplitude)
                # shutil.copy2(os.path.join('../', swathDir, self._insar.amplitude+'.vrt'), self._insar.amplitude+'.vrt')
                # shutil.copy2(os.path.join('../', swathDir, self._insar.amplitude+'.xml'), self._insar.amplitude+'.xml')

                os.rename(os.path.join('../', swathDir, self._insar.interferogram), self._insar.interferogram)
                os.rename(os.path.join('../', swathDir, self._insar.interferogram+'.vrt'), self._insar.interferogram+'.vrt')
                os.rename(os.path.join('../', swathDir, self._insar.interferogram+'.xml'), self._insar.interferogram+'.xml')
                os.rename(os.path.join('../', swathDir, self._insar.amplitude), self._insar.amplitude)
                os.rename(os.path.join('../', swathDir, self._insar.amplitude+'.vrt'), self._insar.amplitude+'.vrt')
                os.rename(os.path.join('../', swathDir, self._insar.amplitude+'.xml'), self._insar.amplitude+'.xml')

                #no need to update frame parameters here
                os.chdir('../')
                #no need to save parameter file here
                os.chdir('../')

                continue

            #choose offsets
            numberOfFrames = len(masterTrack.frames)
            numberOfSwaths = len(masterTrack.frames[i].swaths)
            if self.swathOffsetMatching:
                #no need to do this as the API support 2-d list
                #rangeOffsets = (np.array(self._insar.swathRangeOffsetMatchingMaster)).reshape(numberOfFrames, numberOfSwaths)
                #azimuthOffsets = (np.array(self._insar.swathAzimuthOffsetMatchingMaster)).reshape(numberOfFrames, numberOfSwaths)
                rangeOffsets = self._insar.swathRangeOffsetMatchingMaster
                azimuthOffsets = self._insar.swathAzimuthOffsetMatchingMaster

            else:
                #rangeOffsets = (np.array(self._insar.swathRangeOffsetGeometricalMaster)).reshape(numberOfFrames, numberOfSwaths)
                #azimuthOffsets = (np.array(self._insar.swathAzimuthOffsetGeometricalMaster)).reshape(numberOfFrames, numberOfSwaths)
                rangeOffsets = self._insar.swathRangeOffsetGeometricalMaster
                azimuthOffsets = self._insar.swathAzimuthOffsetGeometricalMaster

            rangeOffsets = rangeOffsets[i]
            azimuthOffsets = azimuthOffsets[i]

            #list of input files
            inputInterferograms = []
            inputAmplitudes = []
            for j, swathNumber in enumerate(range(self._insar.startingSwath, self._insar.endingSwath + 1)):
                swathDir = 's{}'.format(swathNumber)
                inputInterferograms.append(os.path.join('../', swathDir, self._insar.interferogram))
                inputAmplitudes.append(os.path.join('../', swathDir, self._insar.amplitude))

            #note that frame parameters are updated after mosaicking, here no need to update parameters
            #mosaic amplitudes
            swathMosaic(masterTrack.frames[i], inputAmplitudes, self._insar.amplitude, 
                rangeOffsets, azimuthOffsets, self._insar.numberRangeLooks1, self._insar.numberAzimuthLooks1, resamplingMethod=0)
            #mosaic interferograms
            swathMosaic(masterTrack.frames[i], inputInterferograms, self._insar.interferogram, 
                rangeOffsets, azimuthOffsets, self._insar.numberRangeLooks1, self._insar.numberAzimuthLooks1, updateFrame=False, phaseCompensation=True, resamplingMethod=1)

            create_xml(self._insar.amplitude, masterTrack.frames[i].numberOfSamples, masterTrack.frames[i].numberOfLines, 'amp')
            create_xml(self._insar.interferogram, masterTrack.frames[i].numberOfSamples, masterTrack.frames[i].numberOfLines, 'int')

            #update slave frame parameters here, here no need to update parameters
            os.chdir('../')
            #save parameter file, here no need to save parameter file
            os.chdir('../')
        os.chdir('../')


    ############################################################
    # STEP 4. mosaic frames
    ############################################################
    from isceobj.Alos2Proc.runFrameMosaic import frameMosaic
    from isceobj.Alos2Proc.Alos2ProcPublic import create_xml

    for k in range(2):
        os.chdir(ionDir['subband'][k])

        mosaicDir = ionDir['insar']
        if not os.path.exists(mosaicDir):
            os.makedirs(mosaicDir)
        os.chdir(mosaicDir)

        numberOfFrames = len(masterTrack.frames)
        if numberOfFrames == 1:
            import shutil
            frameDir = os.path.join('f1_{}/mosaic'.format(self._insar.masterFrames[0]))
            # if not os.path.isfile(self._insar.interferogram):
            #     os.symlink(os.path.join('../', frameDir, self._insar.interferogram), self._insar.interferogram)
            # #shutil.copy2() can overwrite
            # shutil.copy2(os.path.join('../', frameDir, self._insar.interferogram+'.vrt'), self._insar.interferogram+'.vrt')
            # shutil.copy2(os.path.join('../', frameDir, self._insar.interferogram+'.xml'), self._insar.interferogram+'.xml')
            # if not os.path.isfile(self._insar.amplitude):
            #     os.symlink(os.path.join('../', frameDir, self._insar.amplitude), self._insar.amplitude)
            # shutil.copy2(os.path.join('../', frameDir, self._insar.amplitude+'.vrt'), self._insar.amplitude+'.vrt')
            # shutil.copy2(os.path.join('../', frameDir, self._insar.amplitude+'.xml'), self._insar.amplitude+'.xml')

            os.rename(os.path.join('../', frameDir, self._insar.interferogram), self._insar.interferogram)
            os.rename(os.path.join('../', frameDir, self._insar.interferogram+'.vrt'), self._insar.interferogram+'.vrt')
            os.rename(os.path.join('../', frameDir, self._insar.interferogram+'.xml'), self._insar.interferogram+'.xml')
            os.rename(os.path.join('../', frameDir, self._insar.amplitude), self._insar.amplitude)
            os.rename(os.path.join('../', frameDir, self._insar.amplitude+'.vrt'), self._insar.amplitude+'.vrt')
            os.rename(os.path.join('../', frameDir, self._insar.amplitude+'.xml'), self._insar.amplitude+'.xml')

            #update track parameters, no need to update track parameters here

        else:
            #choose offsets
            if self.frameOffsetMatching:
                rangeOffsets = self._insar.frameRangeOffsetMatchingMaster
                azimuthOffsets = self._insar.frameAzimuthOffsetMatchingMaster
            else:
                rangeOffsets = self._insar.frameRangeOffsetGeometricalMaster
                azimuthOffsets = self._insar.frameAzimuthOffsetGeometricalMaster

            #list of input files
            inputInterferograms = []
            inputAmplitudes = []
            for i, frameNumber in enumerate(self._insar.masterFrames):
                frameDir = 'f{}_{}'.format(i+1, frameNumber)
                inputInterferograms.append(os.path.join('../', frameDir, 'mosaic', self._insar.interferogram))
                inputAmplitudes.append(os.path.join('../', frameDir, 'mosaic', self._insar.amplitude))

            #note that track parameters are updated after mosaicking
            #mosaic amplitudes
            frameMosaic(masterTrack, inputAmplitudes, self._insar.amplitude, 
                rangeOffsets, azimuthOffsets, self._insar.numberRangeLooks1, self._insar.numberAzimuthLooks1, 
                updateTrack=False, phaseCompensation=False, resamplingMethod=0)
            #mosaic interferograms
            frameMosaic(masterTrack, inputInterferograms, self._insar.interferogram, 
                rangeOffsets, azimuthOffsets, self._insar.numberRangeLooks1, self._insar.numberAzimuthLooks1, 
                updateTrack=False, phaseCompensation=True, resamplingMethod=1)

            create_xml(self._insar.amplitude, masterTrack.numberOfSamples, masterTrack.numberOfLines, 'amp')
            create_xml(self._insar.interferogram, masterTrack.numberOfSamples, masterTrack.numberOfLines, 'int')

            #update slave parameters here, no need to update slave parameters here

        os.chdir('../')
        #save parameter file, no need to save parameter file here
        os.chdir('../')


    ############################################################
    # STEP 5. clear frame processing files
    ############################################################
    import shutil
    from isceobj.Alos2Proc.Alos2ProcPublic import runCmd

    for k in range(2):
        os.chdir(ionDir['subband'][k])
        for i, frameNumber in enumerate(self._insar.masterFrames):
            frameDir = 'f{}_{}'.format(i+1, frameNumber)
            shutil.rmtree(frameDir)
            #cmd = 'rm -rf {}'.format(frameDir)
            #runCmd(cmd)
        os.chdir('../')


    ############################################################
    # STEP 6. create differential interferograms
    ############################################################
    import numpy as np
    from isceobj.Alos2Proc.Alos2ProcPublic import runCmd

    for k in range(2):
        os.chdir(ionDir['subband'][k])

        insarDir = ionDir['insar']
        if not os.path.exists(insarDir):
            os.makedirs(insarDir)
        os.chdir(insarDir)

        rangePixelSize = self._insar.numberRangeLooks1 * masterTrack.rangePixelSize
        radarWavelength = subbandRadarWavelength[k]
        rectRangeOffset = os.path.join('../../../', insarDir, self._insar.rectRangeOffset)

        cmd = "imageMath.py -e='a*exp(-1.0*J*b*4.0*{}*{}/{}) * (b!=0)' --a={} --b={} -o {} -t cfloat".format(np.pi, rangePixelSize, radarWavelength, self._insar.interferogram, rectRangeOffset, self._insar.differentialInterferogram)
        runCmd(cmd)

        os.chdir('../../')


    os.chdir('../')
    catalog.printToLog(logger, "runIonSubband")
    self._insar.procDoc.addAllFromCatalog(catalog)


def defineIonDir():
    '''
    define directory names for ionospheric correction
    '''

    ionDir = {
        #swath mosaicking directory
        'swathMosaic' : 'mosaic',
        #final insar processing directory
        'insar' : 'insar',
        #ionospheric correction directory
        'ion' : 'ion',
        #subband directory
        'subband' : ['lower', 'upper'],
        #final ionospheric phase calculation directory
        'ionCal' : 'ion_cal'
        }

    return ionDir


def defineIonFilenames():
    pass







