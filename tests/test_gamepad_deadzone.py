from pathlib import Path
import subprocess
import tempfile
import unittest


class GamepadDeadzoneTests(unittest.TestCase):
    def test_axis_cutoffs_do_not_stack_with_radial_filter_or_rescale_travel(self):
        source=r'''
#include "gamepad.h"
#include <assert.h>
#include <math.h>
static void near(float actual,float expected){assert(fabsf(actual-expected)<0.000001f);}
int main(void){
 PadState pad;gamepad_synth_connect(1);
 gamepad_set_stick_deadzones(.10f,.05f);
 gamepad_synth_axis(PAD_AXIS_LX,.1f);gamepad_synth_axis(PAD_AXIS_LY,-.1f);
 gamepad_synth_axis(PAD_AXIS_RX,.05f);gamepad_synth_axis(PAD_AXIS_RY,-.05f);
 assert(gamepad_read(&pad));for(int i=0;i<4;i++)near(pad.axis[i],0);
 gamepad_synth_axis(PAD_AXIS_LX,nextafterf(.1f,1.f));gamepad_synth_axis(PAD_AXIS_LY,-.5f);
 gamepad_synth_axis(PAD_AXIS_RX,nextafterf(.05f,1.f));gamepad_synth_axis(PAD_AXIS_RY,1.f);
 gamepad_read(&pad);near(pad.axis[PAD_AXIS_LX],nextafterf(.1f,1.f));
 near(pad.axis[PAD_AXIS_LY],-.5f);near(pad.axis[PAD_AXIS_RX],nextafterf(.05f,1.f));near(pad.axis[PAD_AXIS_RY],1);
 gamepad_set_stick_deadzones(-1,-1);gamepad_synth_axis(PAD_AXIS_LX,.5f);gamepad_synth_axis(PAD_AXIS_LY,0);
 gamepad_read(&pad);near(pad.axis[PAD_AXIS_LX],(.5f-.08f)/(1.f-.08f));
 gamepad_set_stick_deadzones(0,-1);gamepad_synth_axis(PAD_AXIS_LX,.001f);gamepad_read(&pad);
 near(pad.axis[PAD_AXIS_LX],.001f);
 gamepad_set_stick_deadzones(.5f,.05f);gamepad_synth_connect(2);
 gamepad_synth_axis(PAD_AXIS_LX,.01f);gamepad_synth_axis(PAD_AXIS_RX,.01f);
 gamepad_synth_axis(PAD_AXIS_LT,.51f);gamepad_read(&pad);
 near(pad.axis[PAD_AXIS_LX],.01f);near(pad.axis[PAD_AXIS_RX],0);near(pad.axis[PAD_AXIS_LT],.5f);
 gamepad_set_stick_deadzones(NAN,INFINITY);gamepad_synth_connect(1);
 gamepad_synth_axis(PAD_AXIS_LX,.5f);gamepad_read(&pad);
 near(pad.axis[PAD_AXIS_LX],(.5f-.08f)/(1.f-.08f));return 0;
}
'''
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);path=root/'check.c';path.write_text(source);binary=root/'check'
            build=subprocess.run(['clang','-O1','-fobjc-arc','-Iruntime',str(path),'runtime/gamepad.m',
                                  '-framework','Foundation','-framework','GameController','-o',str(binary)],
                                 capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True,env={
                'NFSU2_PAD_DEADZONE':'0.08','NFSU2_PAD_TRIGGER_DEADZONE':'0.02'})
            self.assertEqual(run.returncode,0,run.stderr)


if __name__=='__main__':unittest.main()
