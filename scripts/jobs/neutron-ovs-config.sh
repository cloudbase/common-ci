#!/bin/bash

CI_CREDS="neutron-ovs-creds.yaml"
domain_name="neutronovs.local"
domain_user="neutron-ovs"
test_signing="false"
data_port="00:07:43:13:97:c8 00:07:43:13:96:b8 00:07:43:13:a6:08 00:07:43:14:d2:e8 00:07:43:13:f1:48 00:07:43:13:f1:88 00:07:43:13:b3:88 00:07:43:13:b5:18 00:07:43:13:ea:78 00:07:43:13:f1:68 00:07:43:13:9b:f8 00:07:43:14:12:c8 00:07:43:14:12:78 00:07:43:13:f1:58 00:07:43:14:12:88 00:07:43:14:12:98 00:07:43:13:a0:f8 00:07:43:13:9a:78 00:07:43:14:18:18 00:07:43:13:a1:48 00:07:43:14:1f:38 00:07:43:14:1b:48 00:07:43:14:18:38 00:07:43:13:f4:b8 00:07:43:13:98:48 00:07:43:13:f4:f8 00:07:43:14:18:98 00:07:43:13:f1:28 00:07:43:14:1a:18"
external_port="00:07:43:13:97:c0 00:07:43:13:96:b0 00:07:43:13:a6:00 00:07:43:14:d2:e0 00:07:43:13:f1:40 00:07:43:13:f1:80 00:07:43:13:b3:80 00:07:43:13:b5:10 00:07:43:13:ea:70 00:07:43:13:f1:60 00:07:43:13:9b:f0 00:07:43:14:12:c0 00:07:43:14:12:70 00:07:43:13:f1:50 00:07:43:14:12:80 00:07:43:14:12:90 00:07:43:13:a0:f0 00:07:43:13:9a:70 00:07:43:14:18:10 00:07:43:13:a1:40 00:07:43:14:1f:30 00:07:43:14:1b:40 00:07:43:14:18:30 00:07:43:13:f4:b0 00:07:43:13:98:40 00:07:43:13:f4:f0 00:07:43:14:18:90 00:07:43:13:f1:20 00:07:43:14:1a:10"
prep_project="True"
os_data_network="10.31.4.0/23"
disable_ipv6="false"
win_user="Administrator"
win_password=$(< /dev/urandom tr -dc _A-Z-a-z-0-9 | head -c${1:-24};echo;)
ovs_installer="http://10.20.1.14:8080/openvswitch-hyperv-2.6.1-certified.msi"
heat_image_url="http://10.20.1.14:8080/cirros-latest.vhdx"
test_image_url="http://10.20.1.14:8080/cirros-latest.vhdx"
scenario_img="cirros-latest.vhdx"
vmswitch_management="false"
hv_extra_python_packages="setuptools SQLAlchemy==0.9.8 wmi oslo.i18n==1.7.0 pbr==1.2.0 oslo.messaging==4.5.1 lxml==3.6.4"

if [ "$ZUUL_BRANCH" == "master" ]; then
      hyperv_cherry_picks="https://review.openstack.org/openstack/neutron|refs/changes/41/417141/2|master"
      devstack_cherry_picks="https://git.openstack.org/openstack/tempest|refs/changes/49/383049/13|master,https://git.openstack.org/openstack/tempest|refs/changes/28/384528/9|master" 
      post_python_packages="kombu==4.0.1 amqp==2.1.3 SQLAlchemy==1.0.17"
fi


