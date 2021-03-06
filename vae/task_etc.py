import os
import sys
import torch
from torch import nn, optim
from torch .nn import functional as F
from torchvision .utils import save_image as write_image
from model_etc import *
from __.utils import *

# hyperparameters
tasks = ['instruct', 'visualize']
learning_rate = 7e-4
batch_size = 100
epoch_offset = 0
epochs = 1000
log_interval = 10

def load_task (params):
	task_params = params ['task']
	if task_params ['task'] == 'instruct':
		return instruct_task (** task_params)
	elif task_params ['task'] == 'visualize':
		return visualize_task (** task_params)
def save_task (task):
	return (
	{ 'task': { ** task .params, 'epoch_offset': task .epoch_offset, 'rng': torch .get_rng_state (), 'state': task .optimizer and task .optimizer .state_dict () } })

def instruct_task (train_path, test_path, out_path, objective, learning_rate, batch_size, epoch_offset, epochs, log_interval, cuda_ok, seed, rng = None, state = None, ** kwargs):
	objective_fn = vae_objective if objective == 'vae' else panic ('unknown objective ' + params ['objective'])
	os .makedirs (out_path, exist_ok = True)
	if os .listdir (out_path):
		print ('Warning: ' + out_path + ' is not empty!', file = sys .stderr)

	task = thing ()
	task .params = (
		{ 'task': 'instruct'
		, 'train_path': train_path
		, 'test_path': test_path 
		, 'out_path': out_path
		, 'learning_rate': learning_rate 
		, 'batch_size': batch_size 
		, 'epochs': epochs 
		, 'log_interval': log_interval 
		, 'cuda_ok': cuda_ok 
		, 'seed': seed
		, 'objective': objective })
	def file (filename):
		import os
		return os .path .join (out_path, filename)
	def go_instruct (model):
		torch .manual_seed (seed)
		if not rng is None:
			torch .set_rng_state (rng)

		device = torch .device ('cuda') if cuda_ok else torch .device ('cpu')
		model = model .to (device)

		task .optimizer = optim .Adam (model .parameters (), lr = learning_rate)
		if state:
			task .optimizer .load_state_dict (state)

		train_sampler = load_samples (train_path, batch_size, cuda_ok = cuda_ok)
		test_sampler = load_samples (test_path, batch_size, cuda_ok = cuda_ok)

		for epoch in range (epoch_offset, epochs):
			task .epoch_offset = epoch

			i = 0
			epoch_training_loss = 0
			epoch_test_loss = 0
			for status, progress in instruct (model, objective_fn, task .optimizer, train_sampler, test_sampler, device):
				if status == 'train':
					loss = progress
					epoch_training_loss += loss
					i += 1
					if i % log_interval == 0:
						print ('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}' .format (epoch + 1, i * batch_size, len (train_sampler .dataset), 100. * i / len (train_sampler), loss / batch_size))
				elif status == 'trained':
					print ('====> Epoch: {} Average loss: {:.4f}' .format (epoch + 1, epoch_training_loss / len (train_sampler .dataset)))
				elif status == 'test':
					loss = progress
					epoch_test_loss += loss
				elif status == 'tested':
					print ('====> Test set loss: {:.4f}' .format (epoch_test_loss / len (test_sampler .dataset)))

			torch .save (save_task (task), file ('task_' + str (epoch + 1) + '.pt'))
			torch .save (save_model (model), file ('model_' + str (epoch + 1) + '.pt'))

			image_sample, _ = next (test_sampler)
			write_image (comparison_visualization (model, image_sample .to (device), visualization_n), file ('comparison_' + str (epoch + 1) + '.png'))
			encoding_sample = torch .randn (visualization_n ** 2, model .params ['encoding_dimensions'])
			write_image (sampling_visualization (model, encoding_sample .to (device), visualization_n), file ('sampling_' + str (epoch + 1) + '.png'))
	task .go = go_instruct
	return task

def visualize_task (test_path, out_path, epoch_offset, cuda_ok, seed, rng = None, visualization_n = 8, ** kwargs):
	os .makedirs (out_path, exist_ok = True)
	if os .listdir (out_path):
		print ('Warning: ' + out_path + ' is not empty!', file = sys .stderr)

	task = thing ()
	task .params = (
		{ 'task': 'visualize'
		, 'test_path': test_path 
		, 'out_path': out_path
		, 'cuda_ok': cuda_ok 
		, 'seed': seed })
	def file (filename):
		import os
		return os .path .join (out_path, filename)
	def go_visualize (model):
		torch .manual_seed (seed)
		if not rng is None:
			torch .set_rng_state (rng)

		device = torch .device ('cuda') if cuda_ok else torch .device ('cpu')
		model = model .to (device)

		epoch = epoch_offset

		test_sampler = load_samples (test_path, visualization_n, cuda_ok = cuda_ok)

		_, (image_sample, _) = next (enumerate (test_sampler))
		encoding_sample = torch .randn (visualization_n ** 2, model .params ['encoding_dimensions'])

		write_image (comparison_visualization (model, image_sample .to (device), visualization_n), file ('comparison_' + str (epoch + 1) + '.png'))
		write_image (sampling_visualization (model, encoding_sample .to (device), visualization_n), file ('sampling_' + str (epoch + 1) + '.png'))
	task .go = go_visualize
	return task

# Reconstruction + KL divergence losses summed over all elements and batch
def vae_objective (recon_x, x, mu, logvar):
	BCE = F .binary_cross_entropy (recon_x, x .view (* recon_x .size ()), reduction = 'sum')

	# see Appendix B from VAE paper:
	# Kingma and Welling. Auto-Encoding Variational Bayes. ICLR, 2014
	# https://arxiv.org/abs/1312.6114
	# 0.5 * sum (1 + log (sigma^2) - mu^2 - sigma^2)
	KLD = -0.5 * torch .sum (1 + logvar - mu .pow (2) - logvar .exp ())

	return BCE + KLD

def train (model, objective, batch_sample, optimizer):
	model .train ()
	optimizer .zero_grad ()
	reconstructed_sample, mu, logvar = model (batch_sample)
	loss = objective (reconstructed_sample, batch_sample, mu, logvar)
	loss .backward ()
	optimizer .step ()
	return loss .item ()

def test (model, objective, batch_sample):
	model .eval ()
	with torch .no_grad ():
		reconstructed_sample, mu, logvar = model (batch_sample)
		loss = objective (reconstructed_sample, batch_sample, mu, logvar)
		return loss .item ()

def comparison_visualization (model, batch_sample, test_comparison_n):
	model .eval ()
	with torch .no_grad ():
		n = test_comparison_n
		reconstructed_sample, encoding, _ = model (batch_sample)
		lossless_reconstruction = model .decode (encoding)
		comparison = torch .cat (
			[ batch_sample [:n]
			, reconstructed_sample .view (-1, image_channels, image_size [1], image_size [0]) [:n]
			, lossless_reconstruction .view (-1, image_channels, image_size [1], image_size [0]) [:n] ],
			2 )
		return comparison .cpu ()

def sampling_visualization (model, encoding_sample, test_sample_n):
	model .eval ()
	with torch .no_grad ():
		image_sample = model .decode (encoding_sample) .cpu ()
		return image_sample .view (test_sample_n ** 2, image_channels, image_size [1], image_size [0])

def load_samples (path, batch_size, cuda_ok = True):
	import os
	import tempfile
	from torch .utils .data import DataLoader
	from torchvision import datasets, transforms

	image_folder_path = tempfile .TemporaryDirectory () .name
	os .makedirs (image_folder_path)
	os .symlink (os .path .realpath (path), os .path .join (image_folder_path, 'data'))

	cuda_args = {'num_workers': 1, 'pin_memory': True} if cuda_ok else {}
	return DataLoader (
		dataset = datasets .ImageFolder (image_folder_path, transform = transforms .ToTensor ()),
		batch_size = batch_size,
		shuffle = True,
		** cuda_args)

def instruct (model, objective, optimizer, train_sampler, test_sampler, device, visualization_n = 8):
	for i, (batch_sample, _) in enumerate (train_sampler):
		yield 'train', train (model, objective, batch_sample .to (device), optimizer)
	yield 'trained', None

	for i, (batch_sample, _) in enumerate (test_sampler):
		yield 'test', test (model, objective, batch_sample .to (device))
	yield 'tested', None
