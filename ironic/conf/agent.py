# Copyright 2016 Intel Corporation
# Copyright 2014 Rackspace, Inc.
# Copyright 2015 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_config import cfg

from ironic.common.i18n import _


opts = [
    cfg.BoolOpt('manage_agent_boot',
                default=True,
                help=_('Whether Ironic will manage booting of the agent '
                       'ramdisk. If set to False, you will need to configure '
                       'your mechanism to allow booting the agent '
                       'ramdisk.')),
    cfg.IntOpt('memory_consumed_by_agent',
               default=0,
               help=_('The memory size in MiB consumed by agent when it is '
                      'booted on a bare metal node. This is used for '
                      'checking if the image can be downloaded and deployed '
                      'on the bare metal node after booting agent ramdisk. '
                      'This may be set according to the memory consumed by '
                      'the agent ramdisk image.')),
    cfg.BoolOpt('stream_raw_images',
                default=True,
                help=_('Whether the agent ramdisk should stream raw images '
                       'directly onto the disk or not. By streaming raw '
                       'images directly onto the disk the agent ramdisk will '
                       'not spend time copying the image to a tmpfs partition '
                       '(therefore consuming less memory) prior to writing it '
                       'to the disk. Unless the disk where the image will be '
                       'copied to is really slow, this option should be set '
                       'to True. Defaults to True.')),
    cfg.IntOpt('heartbeat_timeout',
               default=300,
               help=_('Maximum interval (in seconds) for agent heartbeats.')),
    cfg.IntOpt('post_deploy_get_power_state_retries',
               default=6,
               help=_('Number of times to retry getting power state to check '
                      'if bare metal node has been powered off after a soft '
                      'power off.')),
    cfg.IntOpt('post_deploy_get_power_state_retry_interval',
               default=5,
               help=_('Amount of time (in seconds) to wait between polling '
                      'power state after trigger soft poweroff.')),
    cfg.StrOpt('agent_api_version',
               default='v1',
               help=_('API version to use for communicating with the ramdisk '
                      'agent.'))
]


def register_opts(conf):
    conf.register_opts(opts, group='agent')